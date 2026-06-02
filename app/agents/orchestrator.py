from app.agents.code_analyzer import CodeAnalyzerAgent
from app.agents.impact_mapper import ImpactMapperAgent
from app.agents.doc_writer   import DocWriterAgent
from app.agents.pr_creator   import PRCreatorAgent
from app.agent_builder.agent  import run_agent
from app.database import get_db
from app.models.pipeline_run import PipelineRun
import time, logging, uuid

logger = logging.getLogger(__name__)

# Set True to use Google Cloud Agent Builder; False to use direct agents
USE_AGENT_BUILDER = False


async def run_pipeline(commit_sha: str, repo_id: int, payload: dict) -> dict:
    db  = get_db()
    run = PipelineRun(repo_id=repo_id, commit_sha=commit_sha)
    await db.pipeline_runs.insert_one(run.dict())
    t0  = time.time()

    try:
        if USE_AGENT_BUILDER:
            # Google Cloud Agent Builder Path
            result = await run_agent(
                session_id=run.run_id,
                commit_sha=commit_sha,
                repo_id=repo_id
            )
        else:
            # Direct Agent Path (dev / fallback)
            result = await _run_direct_agents(run.run_id, commit_sha, repo_id)

        duration = time.time() - t0
        await db.pipeline_runs.update_one(
            {"run_id": run.run_id},
            {"$set": {
                "status": result.get("status", "completed"),
                "mr_url": result.get("mr_url"),
                "duration_seconds": duration
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


async def _run_direct_agents(run_id: str, commit_sha: str, repo_id: int) -> dict:
    """Direct 4-agent pipeline for development and local testing."""
    logger.info(f"[{run_id}] Agent 1: Code Analyzer")
    analysis = await CodeAnalyzerAgent(repo_id, commit_sha).run()

    if not analysis["doc_hints"]:
        return {"status": "skipped", "mr_url": None}

    logger.info(f"[{run_id}] Agent 2: Impact Mapper")
    impact = await ImpactMapperAgent(repo_id, analysis).run()

    if not impact["affected_docs"]:
        return {"status": "skipped", "mr_url": None}

    logger.info(f"[{run_id}] Agent 3: Doc Writer")
    doc_updates = await DocWriterAgent(repo_id, impact, analysis).run()

    if not doc_updates:
        return {"status": "skipped", "mr_url": None}

    logger.info(f"[{run_id}] Agent 4: PR Creator")
    mr = await PRCreatorAgent(repo_id, commit_sha, doc_updates, analysis).run()
    return {"status": "completed", "mr_url": mr["web_url"]}