from app.agents.code_analyzer import CodeAnalyzerAgent
from app.agents.impact_mapper import ImpactMapperAgent
from app.agents.doc_writer   import DocWriterAgent
from app.agents.pr_creator   import PRCreatorAgent
from app.services.github import GitHubClient
from app.database import get_db
from app.models.pipeline_run import PipelineRun
import time, logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def run_pipeline(before_sha: str, after_sha: str, repo_id: int, payload: dict) -> dict:
    db  = get_db()
    run = PipelineRun(repo_id=repo_id, commit_sha=after_sha)
    await db.pipeline_runs.insert_one(run.dict())

    # Extract repository information from GitHub payload
    repository = payload.get("repository", {})
    repo_full_name = repository.get("full_name", "")

    await db.repositories.update_one(
        {"repo_id": repo_id},
        {"$set": {
            "repo_id": repo_id,
            "name":    repository.get("name", ""),
            "full_name": repo_full_name,
            "url":     repository.get("html_url", ""),
            "last_seen": datetime.utcnow(),
        }},
        upsert=True,
    )
    t0  = time.time()

    try:
        result = await _run_direct_agents(run.run_id, before_sha, after_sha, payload)

        duration = time.time() - t0

        # Store per-doc AI output so the feedback loop can diff them later
        doc_details = result.pop("doc_details", [])
        if doc_details:
            await db.pipeline_run_details.insert_many([
                {
                    "run_id":     run.run_id,
                    "doc_path":   d["doc_path"],
                    "ai_written": d["updated_content"],
                }
                for d in doc_details
            ])

        # Persist final run state — includes mr_id and docs_updated
        # so feedback.py can look up the run when the MR is merged.
        await db.pipeline_runs.update_one(
            {"run_id": run.run_id},
            {"$set": {
                "status":           result.get("status", "completed"),
                "mr_url":           result.get("mr_url"),
                "mr_id":            result.get("mr_id"),
                "docs_updated":     result.get("docs_updated", []),
                "duration_seconds": duration,
            }}
        )
        return result

    except Exception as e:
        logger.error(f"[{run.run_id}] Pipeline failed: {e}")
        await db.pipeline_runs.update_one(
            {"run_id": run.run_id},
            {"$set": {"status": "failed", "error_message": str(e)}}
        )
        raise


async def _run_direct_agents(run_id: str, before_sha: str, after_sha: str, payload: dict) -> dict:
    """Direct 4-agent REST pipeline — default path, works with no cloud setup."""

    # Extract GitHub-specific information from payload
    repository = payload.get("repository", {})
    installation = payload.get("installation", {})

    installation_id = installation.get("id")
    if not installation_id:
        raise ValueError("Missing installation.id in GitHub webhook payload")

    full_name = repository.get("full_name", "")
    if "/" not in full_name:
        raise ValueError(f"Invalid repository full_name: {full_name}")

    owner, repo = full_name.split("/", 1)
    default_branch = repository.get("default_branch", "main")

    # Create a single GitHubClient instance to inject into all agents
    client = GitHubClient(
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        default_branch=default_branch
    )

    logger.info(f"[{run_id}] Agent 1: Code Analyzer")
    analysis = await CodeAnalyzerAgent(client, before_sha, after_sha).run()

    if not analysis["doc_hints"]:
        return {"status": "skipped", "mr_url": None, "mr_id": None,
                "docs_updated": [], "doc_details": []}

    logger.info(f"[{run_id}] Agent 2: Impact Mapper")
    impact = await ImpactMapperAgent(client, analysis).run()

    if not impact["affected_docs"]:
        return {"status": "skipped", "mr_url": None, "mr_id": None,
                "docs_updated": [], "doc_details": []}

    logger.info(f"[{run_id}] Agent 3: Doc Writer")
    doc_updates = await DocWriterAgent(client, impact, analysis).run()

    if not doc_updates:
        return {"status": "skipped", "mr_url": None, "mr_id": None,
                "docs_updated": [], "doc_details": []}

    logger.info(f"[{run_id}] Agent 4: PR Creator")
    pr = await PRCreatorAgent(client, after_sha, doc_updates, analysis).run()

    return {
        "status":       "completed",
        "mr_url":       pr["url"],
        "mr_id":        pr.get("number"),
        "docs_updated": [u["doc_path"] for u in doc_updates],
        "doc_details":  doc_updates,                # consumed by run_pipeline, not stored
    }