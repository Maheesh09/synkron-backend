from fastapi import APIRouter, Depends
from app.agents.orchestrator import run_pipeline
from app.services.feedback import process_feedback
from app.security import require_internal_token
from app.models.payloads import RunPipelinePayload, FeedbackPayload

router = APIRouter()


@router.post("/run-pipeline", dependencies=[Depends(require_internal_token)])
async def run_pipeline_endpoint(payload: RunPipelinePayload):
    data = payload.model_dump()
    result = await run_pipeline(
        before_sha=data.get("before"),
        after_sha=data["after"],
        repo_id=data["repository"]["id"],
        payload=data,
    )
    return {"status": result.get("status", "completed"), "mr_url": result.get("mr_url")}


@router.post("/process-feedback", dependencies=[Depends(require_internal_token)])
async def process_feedback_endpoint(payload: FeedbackPayload):
    await process_feedback(payload.model_dump())
    return {"status": "processed"}