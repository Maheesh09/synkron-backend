import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.services.cloud_tasks import enqueue_pipeline, enqueue_feedback
from app.database import get_db

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

@router.post("/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
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
    if delivery_id:
        if await _is_delivery_already_processed(delivery_id):
            logger.info(f"Skipping duplicate delivery {delivery_id} for event {event}")
            return {"status": "already_processed", "delivery_id": delivery_id}

    if event == "push":
        return await _handle_push(payload, background_tasks, delivery_id)

    if event == "pull_request":
        return await _handle_pull_request(payload, background_tasks)

    # installation events come in the next portion.
    return {"status": "ignored", "reason": f"unhandled event: {event}"}


async def _handle_push(payload: dict, background_tasks: BackgroundTasks, delivery_id: str = "") -> dict:
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

    background_tasks.add_task(enqueue_pipeline, payload, delivery_id)
    logger.info(f"Queued pipeline for {repo['full_name']} @ {payload['after'][:8]}")
    return {"status": "accepted"}

async def _handle_pull_request(payload: dict, background_tasks: BackgroundTasks) -> dict:

    pr = payload.get("pull_request", {})

    # Only care about a PR that was actually merged (closed + merged == True).
    if payload.get("action") != "closed" or not pr.get("merged"):
        return {"status": "ignored", "reason": "PR not merged"}

    # And only Synkron's own docs PRs — identified by the branch we created,
    # not by the title. A human can't accidentally trip this.
    head_ref = pr.get("head", {}).get("ref", "")
    if not head_ref.startswith("synkron/docs-"):
        return {"status": "ignored", "reason": "not a synkron docs PR"}

    background_tasks.add_task(enqueue_feedback, payload)
    logger.info(f"Queued feedback for merged docs PR #{pr.get('number')}")
    return {"status": "accepted"}