from fastapi import APIRouter, HTTPException, Query
from app.database import get_db
import secrets
import hashlib

router = APIRouter()


@router.get("/runs")
async def get_recent_runs(limit: int = Query(20, ge=1, le=100)):
    db = get_db()
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

    dur_agg = await db.pipeline_runs.aggregate([
        {"$match": {"status": "completed", "duration_seconds": {"$exists": True}}},
        {"$group": {"_id": None, "avg": {"$avg": "$duration_seconds"}}},
    ]).to_list(length=1)
    avg_duration = round(dur_agg[0]["avg"], 1) if dur_agg else 0

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
    db = get_db()
    repos = await db.repositories.find(
        {}, {"_id": 0, "webhook_token_hash": 0}  # never expose the hash
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

    gitlab_url = body.get("gitlab_url", "").strip().rstrip("/").split("#")[0]
    match = re.search(r"gitlab\.com/(.+)$", gitlab_url)
    if not match:
        raise HTTPException(400, "Provide a full GitLab project URL")

    path = match.group(1)
    mcp  = GitLabMCP()

    #Verify access
    try:
        project = await mcp._get(f"/projects/{path.replace('/', '%2F')}")
    except Exception as e:
        error_str = str(e)
        if "404" in error_str:
            raise HTTPException(422, "Repository not found. Check the URL is correct and the repository is accessible.")
        elif "401" in error_str or "403" in error_str:
            raise HTTPException(422, "Access denied. Ensure your GitLab token has permission to access this repository.")
        else:
            raise HTTPException(422, "Could not connect to the repository. Verify the URL and token permissions.")

    #Generate per-repo token
    webhook_token      = secrets.token_urlsafe(32)
    webhook_token_hash = hashlib.sha256(webhook_token.encode()).hexdigest()
    webhook_url        = f"{settings.SERVICE_URL}/webhook/gitlab/{project['id']}"

    #Save repo to DB
    db = get_db()
    await db.repositories.update_one(
        {"repo_id": project["id"]},
        {"$set": {
            "repo_id":            project["id"],
            "name":               project["name_with_namespace"],
            "url":                project["web_url"],
            "last_seen":          datetime.utcnow().isoformat() + "Z",
            "webhook_token_hash": webhook_token_hash,
        }},
        upsert=True,
    )

    #Prevents duplicate webhooks when a repo is reconnected.
    try:
        existing_hooks = await mcp._get(f"/projects/{path.replace('/', '%2F')}/hooks")
        synkron_prefix = f"{settings.SERVICE_URL}/webhook/gitlab/"
        for hook in existing_hooks:
            if hook.get("url", "").startswith(synkron_prefix):
                await mcp._delete(
                    f"/projects/{path.replace('/', '%2F')}/hooks/{hook['id']}"
                )
    except Exception:
        pass  

    try:
        await mcp._post(
            f"/projects/{path.replace('/', '%2F')}/hooks",
            {
                "url":                     webhook_url,
                "token":                   webhook_token,
                "push_events":             True,
                "merge_requests_events":   True,
                "enable_ssl_verification": True,
            },
        )
    except Exception as e:
        error_str = str(e)
        if "403" in error_str or "401" in error_str:
            raise HTTPException(
                422,
                "Access denied when creating the webhook. "
                "Your GitLab token needs 'api' scope and at least Maintainer "
                "role on the repository to add webhooks.",
            )
        raise HTTPException(422, f"Webhook creation failed: {e}")

    
    return {
        "project_id":     project["id"],
        "name":           project["name_with_namespace"],
        "default_branch": project.get("default_branch", "main"),
        "webhook_url":    webhook_url,        # correct per-repo URL
        "webhook_secret": "auto-configured",  # no manual step needed
        "status":         "ready",
    }


@router.post("/repos/{repo_id}/rotate-token")
async def rotate_webhook_token(repo_id: int):
    """Regenerate the webhook token for a repo. Old token stops working immediately."""
    import re
    from app.services.gitlab_mcp import GitLabMCP
    from app.config import settings

    db   = get_db()
    repo = await db.repositories.find_one({"repo_id": repo_id})
    if not repo:
        raise HTTPException(404, "Repository not found")

    new_token      = secrets.token_urlsafe(32)
    new_token_hash = hashlib.sha256(new_token.encode()).hexdigest()
    webhook_url    = f"{settings.SERVICE_URL}/webhook/gitlab/{repo_id}"

    await db.repositories.update_one(
        {"repo_id": repo_id},
        {"$set": {"webhook_token_hash": new_token_hash}},
    )

    # Update the webhook in GitLab with the new token
    mcp          = GitLabMCP()
    project_path = repo["url"].replace("https://gitlab.com/", "")
    encoded_path = project_path.replace("/", "%2F")

    try:
        existing_hooks = await mcp._get(f"/projects/{encoded_path}/hooks")
        for hook in existing_hooks:
            if hook.get("url", "").startswith(f"{settings.SERVICE_URL}/webhook/gitlab/"):
                await mcp._delete(f"/projects/{encoded_path}/hooks/{hook['id']}")
        await mcp._post(
            f"/projects/{encoded_path}/hooks",
            {
                "url":                     webhook_url,
                "token":                   new_token,
                "push_events":             True,
                "merge_requests_events":   True,
                "enable_ssl_verification": True,
            },
        )
    except Exception:
        pass  # token is rotated in DB regardless — GitLab update is best-effort

    return {
        "webhook_url":    webhook_url,
        "webhook_secret": new_token,
        "status":         "rotated",
    }