from app.agents.code_analyzer import CodeAnalyzerAgent
from app.agents.impact_mapper import ImpactMapperAgent
from app.agents.doc_writer   import DocWriterAgent
from app.agents.pr_creator   import PRCreatorAgent
from app.database import get_db
from app.models.pipeline_run import PipelineRun
import time, logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def run_pipeline(before_sha: str, after_sha: str, repo_id: int, payload: dict) -> dict:
    db  = get_db()
    run = PipelineRun(repo_id=repo_id, commit_sha=after_sha)
    await db.pipeline_runs.insert_one(run.dict())
    project = payload.get("project", {}) or {}
    await db.repositories.update_one(
        {"repo_id": repo_id},
        {"$set": {
            "repo_id": repo_id,
            "name":    project.get("name") or project.get("path_with_namespace"),
            "url":     project.get("web_url"),
            "last_seen": datetime.utcnow(),
        }},
        upsert=True,
    )
    t0  = time.time()

    try:
        result = await _run_direct_agents(run.run_id, before_sha, after_sha, repo_id)

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


async def _run_direct_agents(run_id: str, before_sha: str, after_sha: str, repo_id: int) -> dict:
    """Direct 4-agent REST pipeline — default path, works with no cloud setup."""
    logger.info(f"[{run_id}] Agent 1: Code Analyzer")
    analysis = await CodeAnalyzerAgent(repo_id, before_sha, after_sha).run()

    if not analysis["doc_hints"]:
        return {"status": "skipped", "mr_url": None, "mr_id": None,
                "docs_updated": [], "doc_details": []}

    logger.info(f"[{run_id}] Agent 2: Impact Mapper")
    impact = await ImpactMapperAgent(repo_id, analysis).run()

    if not impact["affected_docs"]:
        return {"status": "skipped", "mr_url": None, "mr_id": None,
                "docs_updated": [], "doc_details": []}

    logger.info(f"[{run_id}] Agent 3: Doc Writer")
    doc_updates = await DocWriterAgent(repo_id, impact, analysis).run()

    if not doc_updates:
        return {"status": "skipped", "mr_url": None, "mr_id": None,
                "docs_updated": [], "doc_details": []}

    logger.info(f"[{run_id}] Agent 4: PR Creator")
    mr = await PRCreatorAgent(repo_id, after_sha, doc_updates, analysis).run()

    return {
        "status":       "completed",
        "mr_url":       mr["web_url"],
        "mr_id":        mr.get("iid"),              # iid = project-level MR number
        "docs_updated": [u["doc_path"] for u in doc_updates],
        "doc_details":  doc_updates,                # consumed by run_pipeline, not stored
    }