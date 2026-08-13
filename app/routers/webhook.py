import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.services.cloud_tasks import enqueue_pipeline, enqueue_feedback
from app.database import get_db
from app.services.rate_limit import check_rate_limit, reserve_rate_limit_quota, release_rate_limit_quota

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_signature(body: bytes, signature_header: str) -> bool:
    """
    Verify a GitHub webhook's HMAC-SHA256 signature.

    GitHub signs the RAW request body with the App's webhook secret and sends
    the result as "sha256=<hex>" in X-Hub-Signature-256. We recompute it over
    the same bytes and compare in constant time, so an attacker can't recover
    the correct value by measuring how long our comparison takes.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


async def _is_delivery_already_processed(delivery_id: str) -> bool:
    """
    Check if this GitHub webhook delivery has already been processed.
    Uses atomic insert to avoid race conditions on concurrent deliveries.
    Returns True if delivery was already seen, False if this is a new delivery.
    """
    db = get_db()
    try:
        await db.webhook_deliveries.insert_one({
            "delivery_id": delivery_id,
            "processed_at": datetime.now(timezone.utc),
        })
        # Successfully inserted = new delivery
        return False
    except DuplicateKeyError:
        # Delivery ID already exists = duplicate/retry
        return True

async def _safe_enqueue(enqueue_coro, delivery_id: str):
    """
    Run the enqueue synchronously so the Cloud Task is created BEFORE we answer
    GitHub. A FastAPI background task can be killed when Cloud Run freezes the
    instance right after the response, silently dropping the event. If the
    enqueue fails, check if a task was actually created (using deterministic
    naming). Only release the idempotency claim if we can confirm no task exists,
    otherwise preserve the claim to avoid duplicate processing. Return 503 so
    GitHub retries if we cannot confirm success.
    """
    from app.services.cloud_tasks import _task_exists
    import asyncio
    try:
        await enqueue_coro
    except Exception as e:
        logging.exception(f"Enqueue failed (delivery {delivery_id}): {e}")
        # Check if the task actually exists despite the error (AlreadyExists or network issue)
        if delivery_id:
            # Check for pipeline task (gh-{delivery_id}) or feedback task (gh-fb-{delivery_id})
            # We need to infer which type based on the coroutine, but since we can't easily
            # introspect, we'll check both patterns
            task_exists_pipeline = await asyncio.to_thread(_task_exists, f"gh-{delivery_id}")
            task_exists_feedback = await asyncio.to_thread(_task_exists, f"gh-fb-{delivery_id}")

            if task_exists_pipeline or task_exists_feedback:
                # Task exists, treat as success
                logger.info(f"Task exists for delivery {delivery_id} despite enqueue error, treating as accepted")
                return

            # No task found, release the claim so GitHub can retry
            try:
                await get_db().webhook_deliveries.delete_one({"delivery_id": delivery_id})
                logger.info(f"Released webhook delivery claim for {delivery_id} (no task found)")
            except Exception as release_err:
                logger.exception(f"Failed to release delivery claim for {delivery_id}: {release_err}")
                # Cannot confirm state, preserve claim and fail
                raise HTTPException(status_code=503, detail="Enqueue failed and state uncertain; preserved claim")
        raise HTTPException(status_code=503, detail="Enqueue failed; GitHub will retry")
        

@router.post("/github")
async def github_webhook(request: Request):
    body = await request.body()                       # raw bytes, for signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    payload = await request.json()                    # same bytes, now parsed

    # GitHub pings the webhook once, right after you save it.
    if event == "ping":
        return {"status": "pong"}

    # Idempotency: deduplicate webhooks using X-GitHub-Delivery header.
    # GitHub retries failed webhooks and allows manual redelivery; without this
    # check we'd create duplicate Cloud Tasks and PipelineRuns for the same commit.
    if delivery_id and await _is_delivery_already_processed(delivery_id):
        logger.info(f"Skipping duplicate delivery {delivery_id} for event {event}")
        return {"status": "already_processed", "delivery_id": delivery_id}

    if event == "push":
        return await _handle_push(payload, delivery_id)

    if event == "pull_request":
        return await _handle_pull_request(payload, delivery_id)

    if event == "installation":
        return await _handle_installation(payload)

    if event == "installation_repositories":
        return await _handle_installation_repositories(payload)

    # installation events come in the next portion.
    return {"status": "ignored", "reason": f"unhandled event: {event}"}


async def _handle_push(payload: dict, delivery_id: str = "") -> dict:
    repo = payload["repository"]
    default_branch = repo["default_branch"]

    # Only react to pushes that land on the default branch.
    if payload.get("ref") != f"refs/heads/{default_branch}":
        return {"status": "ignored", "reason": "not the default branch"}

    commits = payload.get("commits", [])
    if not commits:
        return {"status": "ignored", "reason": "no commits"}

    # Loop guard: never react to Synkron's own work. Its doc commits carry a
    # [synkron] tag, so a merged docs PR won't re-trigger the pipeline.
    if any("[synkron]" in c.get("message", "") for c in commits):
        return {"status": "ignored", "reason": "synkron-authored commit"}

    installation_id = payload.get("installation", {}).get("id")
    if installation_id and not await check_rate_limit(installation_id):
        logger.warning(f"Rate limit exceeded for installation {installation_id}, dropping push")
        return {"status": "rate_limited", "reason": "hourly run limit reached"}

    # Reserve quota before enqueuing
    quota_reserved = False
    if installation_id:
        if not await reserve_rate_limit_quota(installation_id):
            logger.warning(f"Rate limit exceeded for installation {installation_id} during reservation, dropping push")
            return {"status": "rate_limited", "reason": "hourly run limit reached"}
        quota_reserved = True

    try:
        await _safe_enqueue(enqueue_pipeline(payload, delivery_id), delivery_id)
        logger.info(f"Queued pipeline for {repo['full_name']} @ {payload['after'][:8]}")
        return {"status": "accepted"}
    except HTTPException:
        # Release quota if enqueue failed
        if quota_reserved and installation_id:
            await release_rate_limit_quota(installation_id)
        raise

async def _handle_pull_request(payload: dict, delivery_id: str = "") -> dict:

    pr = payload.get("pull_request", {})

    # Only care about a PR that was actually merged (closed + merged == True).
    if payload.get("action") != "closed" or not pr.get("merged"):
        return {"status": "ignored", "reason": "PR not merged"}

    # And only Synkron's own docs PRs — identified by the branch we created,
    # not by the title. A human can't accidentally trip this.
    head_ref = pr.get("head", {}).get("ref", "")
    if not head_ref.startswith("synkron/docs-"):
        return {"status": "ignored", "reason": "not a synkron docs PR"}

    await _safe_enqueue(enqueue_feedback(payload, delivery_id), delivery_id)
    logger.info(f"Queued feedback for merged docs PR #{pr.get('number')}")
    return {"status": "accepted"}


async def _upsert_repos(db, repos, installation_id, account_id, account_login):
    for r in repos:
        await db.repositories.update_one(
            {"repo_id": r["id"]},
            {"$set": {
                "repo_id":         r["id"],
                "full_name":       r["full_name"],
                "name":            r["name"],
                "owner":           account_login,
                "account_id":      account_id,
                "installation_id": installation_id,
            }},
            upsert=True,
        )


async def _handle_installation(payload: dict) -> dict:
    action          = payload.get("action")
    installation    = payload.get("installation", {})
    installation_id = installation.get("id")
    account         = installation.get("account", {})
    account_id      = account.get("id")
    account_login   = account.get("login")
    db = get_db()

    if action == "created":
        repos = payload.get("repositories", [])
        await _upsert_repos(db, repos, installation_id, account_id, account_login)
        logger.info(f"Installation {installation_id} created for {account_login} ({len(repos)} repos)")
        return {"status": "accepted", "repos": len(repos)}

    if action == "deleted":
        result = await db.repositories.delete_many({"installation_id": installation_id})
        logger.info(f"Installation {installation_id} deleted; removed {result.deleted_count} repos")
        return {"status": "accepted", "removed": result.deleted_count}

    # suspend / unsuspend / new_permissions_accepted — no-op for now
    return {"status": "ignored", "reason": f"installation action: {action}"}     


async def _handle_installation_repositories(payload: dict) -> dict:
    action          = payload.get("action")
    installation    = payload.get("installation", {})
    installation_id = installation.get("id")
    account         = installation.get("account", {})
    account_id      = account.get("id")
    account_login   = account.get("login")
    db = get_db()

    if action == "added":
        repos = payload.get("repositories_added", [])
        await _upsert_repos(db, repos, installation_id, account_id, account_login)
        return {"status": "accepted", "added": len(repos)}

    if action == "removed":
        removed = payload.get("repositories_removed", [])
        ids = [r["id"] for r in removed]
        result = await db.repositories.delete_many({
            "repo_id": {"$in": ids},
            "installation_id": installation_id,
        })
        return {"status": "accepted", "removed": result.deleted_count}

    return {"status": "ignored", "reason": f"installation_repositories action: {action}"}   