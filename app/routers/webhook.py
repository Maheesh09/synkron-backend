import hashlib
import hmac
import logging

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from app.config import settings
from app.services.cloud_tasks import enqueue_pipeline, enqueue_feedback

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

@router.post("/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()                       # raw bytes, for signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()                    # same bytes, now parsed

    # GitHub pings the webhook once, right after you save it.
    if event == "ping":
        return {"status": "pong"}

    if event == "push":
        return await _handle_push(payload, background_tasks)

    # pull_request (feedback) and installation events come in the next portion.
    return {"status": "ignored", "reason": f"unhandled event: {event}"}


async def _handle_push(payload: dict, background_tasks: BackgroundTasks) -> dict:
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

    background_tasks.add_task(enqueue_pipeline, payload)
    logger.info(f"Queued pipeline for {repo['full_name']} @ {payload['after'][:8]}")
    return {"status": "accepted"}