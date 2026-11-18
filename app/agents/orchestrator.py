from app.agents.code_analyzer import CodeAnalyzerAgent
from app.agents.impact_mapper import ImpactMapperAgent
from app.agents.doc_writer   import DocWriterAgent
from app.agents.pr_creator   import PRCreatorAgent
from app.services.github import GitHubClient
from app.database import get_db
from app.models.pipeline_run import PipelineRun
from app.services.errors import PipelineRetry, is_retryable
from app.services.gemini import start_usage_tracking, get_usage
from datetime import datetime
import time, logging

logger = logging.getLogger(__name__)


async def _start_run(db, repo_id: int, after_sha: str, task_name: str | None) -> str:
    """Create the run record, or reuse it when Cloud Tasks retries the same
    task, so one push maps to one run however many attempts it takes.
    last_attempt_at lets the sweeper tell a stalled run from one still retrying."""
    now = datetime.utcnow()
    if task_name:
        existing = await db.pipeline_runs.find_one({"task_name": task_name})
        if existing:
            await db.pipeline_runs.update_one(
                {"run_id": existing["run_id"]},
                {"$set": {"status": "running", "last_attempt_at": now},
                 "$inc": {"attempts": 1}},
            )
            return existing["run_id"]

    run = PipelineRun(repo_id=repo_id, commit_sha=after_sha)
    doc = run.dict()
    doc.update({"task_name": task_name, "attempts": 1, "last_attempt_at": now})
    await db.pipeline_runs.insert_one(doc)
    return run.run_id


async def run_pipeline(before_sha: str, after_sha: str, repo_id: int, payload: dict,
                       task_name: str | None = None, final_attempt: bool = True) -> dict:
    """
    Run the agents for one push.

    Retryable errors on a non-final attempt raise PipelineRetry (the endpoint
    turns that into 503 so Cloud Tasks tries again) and leave the run open.
    Anything else, or any error on the final attempt, marks the run failed and
    returns {"status": "failed"} so the task is acknowledged.
    """
    db     = get_db()
    run_id = await _start_run(db, repo_id, after_sha, task_name)

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

    start_usage_tracking()
    t0 = time.perf_counter()

    try:
        result = await _run_direct_agents(run_id, before_sha, after_sha, payload)
        duration = time.perf_counter() - t0
        usage = get_usage()

        doc_details = result.pop("doc_details", [])
        stage_ms = result.pop("stage_ms", {})
        # Upsert, not insert: a retried task may already have written these.
        for d in doc_details:
            await db.pipeline_run_details.update_one(
                {"run_id": run_id, "doc_path": d["doc_path"]},
                {"$set": {
                    "repo_id":    repo_id,
                    "ai_written": d["updated_content"],
                    "merged":     None,      # set by the feedback loop
                }},
                upsert=True,
            )

        await db.pipeline_runs.update_one(
            {"run_id": run_id},
            {"$set": {
                "status":           result.get("status", "completed"),
                "skip_reason":      result.get("skip_reason"),
                "mr_url":           result.get("mr_url"),
                "mr_id":            result.get("mr_id"),
                "docs_updated":     result.get("docs_updated", []),
                "duration_seconds": round(duration, 3),
                "stage_ms":         stage_ms,
                "tokens_total":     usage.get("total_tokens", 0),
                "cost_usd":         usage.get("cost_usd", 0.0),
                "gemini_calls":     usage.get("calls", 0),
            }}
        )
        logger.info(
            f"[{run_id}] done in {duration:.1f}s stages={stage_ms} "
            f"tokens={usage.get('total_tokens', 0)} cost=${usage.get('cost_usd', 0):.5f}"
        )
        return result

    except Exception as e:
        duration = time.perf_counter() - t0
        error = {"error_type": type(e).__name__, "error_message": str(e),
                 "duration_seconds": round(duration, 3)}

        if is_retryable(e) and not final_attempt:
            logger.warning(f"[{run_id}] Retryable failure after {duration:.1f}s, "
                           f"asking Cloud Tasks to retry: {e}")
            # Keep the run open; record why this attempt failed.
            await db.pipeline_runs.update_one(
                {"run_id": run_id},
                {"$set": {f"last_{k}": v for k, v in error.items()}},
            )
            raise PipelineRetry(e) from e

        logger.error(f"[{run_id}] Pipeline failed after {duration:.1f}s: {e}")
        await db.pipeline_runs.update_one(
            {"run_id": run_id},
            {"$set": {"status": "failed", **error}},
        )
        return {"status": "failed", "error_type": error["error_type"], "mr_url": None}


async def _run_direct_agents(run_id: str, before_sha: str, after_sha: str, payload: dict) -> dict:
    """Direct 4-agent REST pipeline — default path, works with no cloud setup."""

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

    client = GitHubClient(
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        default_branch=default_branch,
    )

    stage_ms: dict = {}

    def _skipped(reason: str) -> dict:
        return {"status": "skipped", "skip_reason": reason, "mr_url": None,
                "mr_id": None, "docs_updated": [], "doc_details": [],
                "stage_ms": stage_ms}

    _t = time.perf_counter()
    logger.info(f"[{run_id}] Agent 1: Code Analyzer")
    analysis = await CodeAnalyzerAgent(client, before_sha, after_sha).run()
    stage_ms["code_analyzer"] = round((time.perf_counter() - _t) * 1000)

    if not analysis["doc_hints"]:
        return _skipped("no_doc_hints")

    _t = time.perf_counter()
    logger.info(f"[{run_id}] Agent 2: Impact Mapper")
    impact = await ImpactMapperAgent(client, analysis).run()
    stage_ms["impact_mapper"] = round((time.perf_counter() - _t) * 1000)

    if not impact["affected_docs"]:
        return _skipped("no_affected_docs")

    _t = time.perf_counter()
    logger.info(f"[{run_id}] Agent 3: Doc Writer")
    doc_updates = await DocWriterAgent(client, impact, analysis).run()
    stage_ms["doc_writer"] = round((time.perf_counter() - _t) * 1000)

    if not doc_updates:
        return _skipped("no_doc_updates")

    _t = time.perf_counter()
    logger.info(f"[{run_id}] Agent 4: PR Creator")
    pr = await PRCreatorAgent(client, after_sha, doc_updates, analysis).run()
    stage_ms["pr_creator"] = round((time.perf_counter() - _t) * 1000)

    return {
        "status":       "completed",
        "skip_reason":  None,
        "mr_url":       pr["url"],
        "mr_id":        pr.get("number"),
        "docs_updated": [u["doc_path"] for u in doc_updates],
        "doc_details":  doc_updates,
        "stage_ms":     stage_ms,
    }