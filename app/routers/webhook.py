from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from app.services.cloud_tasks import enqueue_pipeline, enqueue_feedback
from app.config import settings
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/gitlab")
async def gitlab_webhook(request: Request, background_tasks: BackgroundTasks):
    # 1. Validate secret token
    token = request.headers.get("X-Gitlab-Token")
    if token != settings.GITLAB_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()
    event   = request.headers.get("X-Gitlab-Event", "")

    if event == "Push Hook":
        # 2. Skip empty pushes (branch deletes)
        if payload.get("total_commits_count", 0) == 0:
            return {"status": "ignored", "reason": "no commits"}

        # 3. CRITICAL: Skip our own bot commits — prevents infinite loops
        if payload.get("user_username") == "synkron-bot":
            return {"status": "ignored", "reason": "synkron commit"}

        # 4. Queue the pipeline — don't run it here
        background_tasks.add_task(enqueue_pipeline, payload)
        logger.info(f"Queued pipeline for repo {payload.get('project',{}).get('id')}")

    elif event == "Merge Request Hook":
        action = payload.get("object_attributes", {}).get("action")
        title  = payload.get("object_attributes", {}).get("title", "")
        # 5. Capture human edits on Synkron's MRs for the feedback loop
        if action == "merge" and "Docs:" in title:
            background_tasks.add_task(enqueue_feedback, payload)

    return {"status": "accepted"}  # Always 200 immediately