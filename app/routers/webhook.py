from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Path
from app.services.cloud_tasks import enqueue_pipeline, enqueue_feedback
from app.config import settings
from app.database import get_db
import hashlib, logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/gitlab/{project_id}")
async def gitlab_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    project_id: int = Path(...),
):
    db   = get_db()
    repo = await db.repositories.find_one({"repo_id": project_id})

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not registered")

    incoming_hash = hashlib.sha256(
        request.headers.get("X-Gitlab-Token", "").encode()
    ).hexdigest()

    if incoming_hash != repo.get("webhook_token_hash", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()
    event   = request.headers.get("X-Gitlab-Event", "")

    if event == "Push Hook":
        if payload.get("total_commits_count", 0) == 0:
            return {"status": "ignored", "reason": "no commits"}
        if payload.get("user_username") == "synkron-bot":
            return {"status": "ignored", "reason": "synkron commit"}
        background_tasks.add_task(enqueue_pipeline, payload)
        logger.info(f"Queued pipeline for repo {project_id}")

    elif event == "Merge Request Hook":
        action = payload.get("object_attributes", {}).get("action")
        title  = payload.get("object_attributes", {}).get("title", "")
        if action == "merge" and "Docs:" in title:
            background_tasks.add_task(enqueue_feedback, payload)

    return {"status": "accepted"}