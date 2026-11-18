from fastapi import APIRouter, Depends, Header, HTTPException
from app.agents.orchestrator import run_pipeline
from app.config import settings
from app.services.errors import PipelineRetry
from app.services.feedback import process_feedback
from app.services.sweeper import sweep_abandoned_runs
from app.security import require_internal_token
from app.models.payloads import RunPipelinePayload, FeedbackPayload

router = APIRouter()


@router.post("/run-pipeline", dependencies=[Depends(require_internal_token)])
async def run_pipeline_endpoint(
    payload: RunPipelinePayload,
    # Set by Cloud Tasks; absent when called directly (LOCAL_DEV, manual curl).
    x_cloudtasks_taskname: str | None = Header(None),
    x_cloudtasks_taskretrycount: int | None = Header(None),
):
    """
    Contract with Cloud Tasks: 503 means "retry this task", 200 means "done",
    including runs that failed permanently (they are recorded as failed).
    """
    data = payload.model_dump()
    retry_count = x_cloudtasks_taskretrycount
    final_attempt = retry_count is None or retry_count + 1 >= settings.PIPELINE_MAX_ATTEMPTS
    try:
        result = await run_pipeline(
            before_sha=data.get("before"),
            after_sha=data["after"],
            repo_id=data["repository"]["id"],
            payload=data,
            task_name=x_cloudtasks_taskname,
            final_attempt=final_attempt,
        )
    except PipelineRetry as e:
        raise HTTPException(status_code=503, detail=f"Retryable failure: {e}")
    return {"status": result.get("status", "completed"), "mr_url": result.get("mr_url")}


@router.post("/process-feedback", dependencies=[Depends(require_internal_token)])
async def process_feedback_endpoint(payload: FeedbackPayload):
    await process_feedback(payload.model_dump())
    return {"status": "processed"}

@router.post("/sweep", dependencies=[Depends(require_internal_token)])
async def sweep_endpoint():
    """Called by Cloud Scheduler every 15 minutes (see README)."""
    return {"status": "ok", "abandoned": await sweep_abandoned_runs()}
