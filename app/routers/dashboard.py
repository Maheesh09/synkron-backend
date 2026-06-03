from fastapi import APIRouter
from app.database import get_db

router = APIRouter()


@router.get("/runs")
async def get_recent_runs(limit: int = 20):
    db   = get_db()
    runs = await db.pipeline_runs.find(
        {}, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(length=limit)
    return runs


@router.get("/health")
async def get_health_stats():
    db        = get_db()
    total     = await db.pipeline_runs.count_documents({})
    completed = await db.pipeline_runs.count_documents({"status": "completed"})
    skipped   = await db.pipeline_runs.count_documents({"status": "skipped"})
    return {
        "total_runs":    total,
        "completed_runs": completed,
        "skipped_runs":  skipped,
        "success_rate":  round(completed / total * 100, 1) if total > 0 else 0
    }


@router.get("/repos")
async def get_repositories():
    db   = get_db()
    repos = await db.repositories.find(
        {}, {"_id": 0}
    ).to_list(length=50)
    return repos