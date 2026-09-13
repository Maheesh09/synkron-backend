from fastapi import APIRouter, Query, Depends
from app.database import get_db
from app.auth import get_current_github_id

router = APIRouter()


async def _user_repo_ids(db, github_id: int) -> list:
    """repo_ids the signed-in user owns (via their GitHub account), to scope runs/health."""
    cursor = db.repositories.find({"account_id": github_id}, {"_id": 0, "repo_id": 1})
    return [r["repo_id"] async for r in cursor]


@router.get("/runs")
async def get_recent_runs(
    limit: int = Query(20, ge=1, le=100),
    github_id: int = Depends(get_current_github_id),
):
    db = get_db()
    repo_ids = await _user_repo_ids(db, github_id)
    if not repo_ids:
        return []
    runs = await db.pipeline_runs.find(
        {"repo_id": {"$in": repo_ids}}, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(length=limit)
    return runs


@router.get("/health")
async def get_health_stats(github_id: int = Depends(get_current_github_id)):
    db = get_db()
    repo_ids = await _user_repo_ids(db, github_id)
    if not repo_ids:
        return {
            "total_runs": 0, "completed_runs": 0, "skipped_runs": 0,
            "success_rate": 0, "avg_duration": 0, "docs_updated": 0,
        }

    scope     = {"repo_id": {"$in": repo_ids}}
    total     = await db.pipeline_runs.count_documents(scope)
    completed = await db.pipeline_runs.count_documents({**scope, "status": "completed"})
    skipped   = await db.pipeline_runs.count_documents({**scope, "status": "skipped"})

    dur_agg = await db.pipeline_runs.aggregate([
        {"$match": {**scope, "status": "completed", "duration_seconds": {"$exists": True}}},
        {"$group": {"_id": None, "avg": {"$avg": "$duration_seconds"}}},
    ]).to_list(length=1)
    avg_duration = round(dur_agg[0]["avg"], 1) if dur_agg else 0

    docs_agg = await db.pipeline_runs.aggregate([
        {"$match": {**scope, "docs_updated": {"$exists": True}}},
        {"$group": {"_id": None, "total": {"$sum": {"$size": "$docs_updated"}}}},
    ]).to_list(length=1)
    docs_updated = docs_agg[0]["total"] if docs_agg else 0

    lat_agg = await db.pipeline_runs.aggregate([
        {"$match": {**scope, "status": "completed", "duration_seconds": {"$exists": True}}},
        {"$group": {
            "_id": None,
            "durations": {"$push": "$duration_seconds"},
            "cost": {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$tokens_total"},
        }},
    ]).to_list(length=1)

    p50 = p95 = 0.0
    total_cost = total_tokens = 0
    if lat_agg:
        d = sorted(lat_agg[0]["durations"])
        if d:
            p50 = round(d[int(len(d) * 0.50)], 1)
            p95 = round(d[min(int(len(d) * 0.95), len(d) - 1)], 1)
        total_cost = round(lat_agg[0].get("cost") or 0, 4)
        total_tokens = lat_agg[0].get("tokens") or 0

    return {
        "total_runs":     total,
        "completed_runs": completed,
        "skipped_runs":   skipped,
        "success_rate":   round(completed / total * 100, 1) if total > 0 else 0,
        "avg_duration":   avg_duration,
        "docs_updated":   docs_updated,
        "p50_duration":   p50,
        "p95_duration":   p95,
        "total_cost":     total_cost,
        "total_tokens":   total_tokens,
    }


@router.get("/repos")
async def get_repositories(github_id: int = Depends(get_current_github_id)):
    db = get_db()
    repos = await db.repositories.find(
        {"account_id": github_id},
        {"_id": 0, "account_id": 0, "installation_id": 0,
         "webhook_token_hash": 0, "owner_uid": 0},   # internal / legacy — never expose
    ).to_list(length=50)
    return repos