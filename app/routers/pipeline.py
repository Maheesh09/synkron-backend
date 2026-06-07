from fastapi import APIRouter, Header, HTTPException
from app.agents.orchestrator import run_pipeline
from app.services.feedback import process_feedback
from app.config import settings

router = APIRouter()


@router.post("/run-pipeline")
async def run_pipeline_endpoint(payload: dict, x_internal_token: str = Header(None)):
    if x_internal_token != settings.INTERNAL_SECRET:
        raise HTTPException(status_code=403)
    result = await run_pipeline(
        before_sha=payload("before"),
        after_sha=payload["after"],
        repo_id=payload["project"]["id"],
        payload=payload
    )
    return {"status": "completed", "mr_url": result.get("mr_url")}


@router.post("/process-feedback")
async def process_feedback_endpoint(payload: dict, x_internal_token: str = Header(None)):
    if x_internal_token != settings.INTERNAL_SECRET:
        raise HTTPException(status_code=403)
    await process_feedback(payload)
    return {"status": "processed"}