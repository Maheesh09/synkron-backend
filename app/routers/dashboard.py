from fastapi import APIRouter, HTTPException, Query, Depends
from app.database import get_db
from app.auth import get_current_uid
import secrets
import hashlib

router = APIRouter()


async def _user_repo_ids(db, uid: str) -> list:
    """Return the repo_ids owned by this user (used to scope runs/health)."""
    cursor = db.repositories.find({"owner_uid": uid}, {"_id": 0, "repo_id": 1})
    return [r["repo_id"] async for r in cursor]


@router.get("/runs")
async def get_recent_runs(
    limit: int = Query(20, ge=1, le=100),
    uid: str = Depends(get_current_uid),
):
    db = get_db()
    repo_ids = await _user_repo_ids(db, uid)
    if not repo_ids:
        return []
    runs = await db.pipeline_runs.find(
        {"repo_id": {"$in": repo_ids}}, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(length=limit)
    return runs


@router.get("/health")
async def get_health_stats(uid: str = Depends(get_current_uid)):
    db = get_db()
    repo_ids = await _user_repo_ids(db, uid)
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

    return {
        "total_runs":     total,
        "completed_runs": completed,
        "skipped_runs":   skipped,
        "success_rate":   round(completed / total * 100, 1) if total > 0 else 0,
        "avg_duration":   avg_duration,
        "docs_updated":   docs_updated,
    }


@router.get("/repos")
async def get_repositories(uid: str = Depends(get_current_uid)):
    db = get_db()
    repos = await db.repositories.find(
        {"owner_uid": uid},
        {"_id": 0, "webhook_token_hash": 0, "owner_uid": 0},  # never expose hash or owner
    ).to_list(length=50)
    return repos


@router.delete("/repos/{repo_id}")
async def delete_repository(repo_id: int, uid: str = Depends(get_current_uid)):
    db = get_db()
    result = await db.repositories.delete_one({"repo_id": repo_id, "owner_uid": uid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Repository not found")
    return {"status": "success"}


@router.post("/repos/connect")
async def connect_repo(body: dict, uid: str = Depends(get_current_uid)):
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

    # Verify access
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

    db = get_db()

    # A repo can only belong to one account. Block hijacking someone else's repo.
    existing = await db.repositories.find_one({"repo_id": project["id"]})
    if existing and existing.get("owner_uid") and existing["owner_uid"] != uid:
        raise HTTPException(409, "This repository is already connected by another account.")

    # Generate per-repo webhook token
    webhook_token      = secrets.token_urlsafe(32)
    webhook_token_hash = hashlib.sha256(webhook_token.encode()).hexdigest()
    webhook_url        = f"{settings.SERVICE_URL}/webhook/gitlab/{project['id']}"

    # Save repo to DB (owned by the current user)
    await db.repositories.update_one(
        {"repo_id": project["id"]},
        {"$set": {
            "repo_id":            project["id"],
            "owner_uid":          uid,
            "name":               project["name_with_namespace"],
            "url":                project["web_url"],
            "last_seen":          datetime.utcnow().isoformat() + "Z",
            "webhook_token_hash": webhook_token_hash,
        }},
        upsert=True,
    )

    # Prevent duplicate webhooks when a repo is reconnected.
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
                "url":                       webhook_url,
                "token":                     webhook_token,
                "push_events":               True,
                "push_events_branch_filter": project.get("default_branch", "main"),
                "merge_requests_events":     True,
                "enable_ssl_verification":   True,
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
        "webhook_url":    webhook_url,
        "webhook_secret": "auto-configured",
        "status":         "ready",
    }


@router.post("/repos/{repo_id}/rotate-token")
async def rotate_webhook_token(repo_id: int, uid: str = Depends(get_current_uid)):
    """Regenerate the webhook token for a repo. Old token stops working immediately."""
    from app.services.gitlab_mcp import GitLabMCP
    from app.config import settings

    db   = get_db()
    repo = await db.repositories.find_one({"repo_id": repo_id, "owner_uid": uid})
    if not repo:
        raise HTTPException(404, "Repository not found")

    new_token      = secrets.token_urlsafe(32)
    new_token_hash = hashlib.sha256(new_token.encode()).hexdigest()
    webhook_url    = f"{settings.SERVICE_URL}/webhook/gitlab/{repo_id}"

    await db.repositories.update_one(
        {"repo_id": repo_id, "owner_uid": uid},
        {"$set": {"webhook_token_hash": new_token_hash}},
    )

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
        pass  # token rotated in DB regardless — GitLab update is best-effort

    return {
        "project_id":     repo_id,
        "webhook_url":    webhook_url,
        "webhook_secret": new_token,
        "status":         "ready",
    }