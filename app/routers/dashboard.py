from fastapi import APIRouter, HTTPException
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

    # Avg duration of completed runs
    dur_agg = await db.pipeline_runs.aggregate([
        {"$match": {"status": "completed", "duration_seconds": {"$exists": True}}},
        {"$group": {"_id": None, "avg": {"$avg": "$duration_seconds"}}},
    ]).to_list(length=1)
    avg_duration = round(dur_agg[0]["avg"], 1) if dur_agg else 0

    # Total docs updated across all runs
    docs_agg = await db.pipeline_runs.aggregate([
        {"$match": {"docs_updated": {"$exists": True}}},
        {"$group": {"_id": None, "total": {"$sum": {"$size": "$docs_updated"}}}},
    ]).to_list(length=1)
    docs_updated = docs_agg[0]["total"] if docs_agg else 0

    return {
        "total_runs":     total,
        "completed_runs": completed,
        "skipped_runs":   skipped,
        "success_rate":   round(completed / total * 100, 1) if total > 0 else 0,
        "avg_duration":   avg_duration,
        "docs_updated":   docs_updated,
    }


@router.get("/repos")
async def get_repositories():
    db   = get_db()
    repos = await db.repositories.find(
        {}, {"_id": 0}
    ).to_list(length=50)
    return repos

@router.delete("/repos/{repo_id}")
async def delete_repository(repo_id: int):
    db = get_db()
    result = await db.repositories.delete_one({"repo_id": repo_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Repository not found")
    return {"status": "success"}

@router.post("/repos/connect")
async def connect_repo(body: dict):
    import re
    from datetime import datetime
    from app.services.gitlab_mcp import GitLabMCP
    from app.config import settings

    gitlab_url = body.get("gitlab_url", "").strip().rstrip("/")
    # Extract project path from URL
    match = re.search(r"gitlab\.com/(.+)$", gitlab_url)
    if not match:
        raise HTTPException(400, "Provide a full GitLab project URL")

    path = match.group(1)
    mcp = GitLabMCP()

    try:
        project = await mcp._get(f"/projects/{path.replace('/', '%2F')}")
    except Exception as e:
        raise HTTPException(422, f"Cannot access project: {e}")

    # Insert or update the repository in the database directly
    # This bypasses the need to wait for a webhook push to discover the repo
    db = get_db()
    repo_doc = {
        "repo_id": project["id"],
        "name": project["name_with_namespace"],
        "url": project["web_url"],
        "last_seen": datetime.utcnow().isoformat() + "Z"
    }
    await db.repositories.update_one(
        {"repo_id": project["id"]},
        {"$set": repo_doc},
        upsert=True
    )

    return {
        "project_id":     project["id"],
        "name":           project["name_with_namespace"],
        "default_branch": project.get("default_branch", "main"),
        "webhook_url":    f"{settings.SERVICE_URL}/webhook/gitlab",
        "webhook_secret": settings.GITLAB_WEBHOOK_SECRET[:4] + "••••",
        "status":         "ready"
    }