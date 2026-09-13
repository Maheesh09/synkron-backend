from app.services.github import GitHubClient
from app.database import get_db
from app.models.pipeline_run import CorrectionPattern
import difflib, logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def process_feedback(payload: dict):
    """
    Process feedback from a merged Synkron docs PR.
    Compares what Synkron wrote vs. what the human merged, storing corrections
    as few-shot examples for future runs.
    """
    db = get_db()

    # Extract GitHub PR information
    pr = payload.get("pull_request", {})
    repository = payload.get("repository", {})
    installation = payload.get("installation", {})

    pr_number = pr.get("number")
    repo_id = repository.get("id")
    installation_id = installation.get("id")

    if not all([pr_number, repo_id, installation_id]):
        logger.warning("Missing required fields in PR feedback payload")
        return

    # Find the pipeline run linked to this merged PR
    run = await db.pipeline_runs.find_one({"mr_id": pr_number, "repo_id": repo_id})
    await db.pipeline_runs.update_one(
        {"run_id": run["run_id"]},
        {"$set": {"merged_at": datetime.now(timezone.utc)}}
    )
    if not run:
        logger.info(f"No pipeline run found for PR #{pr_number} in repo {repo_id}")
        return

    # Extract owner/repo for GitHubClient
    full_name = repository.get("full_name", "")
    if "/" not in full_name:
        logger.error(f"Invalid repository full_name: {full_name}")
        return

    owner, repo = full_name.split("/", 1)
    default_branch = repository.get("default_branch", "main")

    # Create GitHub client
    client = GitHubClient(
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        default_branch=default_branch
    )

    # Use a stable repo key for correction patterns (owner/repo instead of numeric ID)
    # This allows patterns to work even if the numeric ID changes
    repo_key = f"{owner}/{repo}"

    for doc_path in run.get("docs_updated", []):
        try:
            # Get what was merged (human-edited version)
            merged_content = await client.get_file_content(doc_path)

            # Get what Synkron originally wrote
            run_detail = await db.pipeline_run_details.find_one(
                {"run_id": run["run_id"], "doc_path": doc_path}
            )
            if not run_detail:
                continue

            ai_content = run_detail["ai_written"]

            # Accepted verbatim. Record it — an unmarked doc would otherwise be
            # indistinguishable from a PR that was never merged at all.
            if ai_content.strip() == merged_content.strip():
                await db.pipeline_run_details.update_one(
                    {"run_id": run["run_id"], "doc_path": doc_path},
                    {"$set": {"merged": True, "edited": False}}
                )
                continue

            # Compute the diff (what the human changed)
            delta = "\n".join(difflib.unified_diff(
                ai_content.splitlines(),
                merged_content.splitlines(),
                lineterm="", n=2
            ))

            # Classify doc type for better retrieval
            p = doc_path.lower()
            doc_type = (
                "readme"         if "readme" in p else
                "api_reference"  if "api" in p    else
                "authentication" if "auth" in p   else
                "general"
            )

            # Store correction as a future few-shot example
            # Store both numeric repo_id (for consistency with PipelineRun) and
            # string repo_key (owner/repo) for stable querying across GitHub installs
            pattern = CorrectionPattern(
                repo_id=repo_id,
                run_id=run["run_id"],
                repo_key=repo_key,
                mr_id=pr_number,
                doc_path=doc_path, doc_type=doc_type,
                ai_written=ai_content,
                human_corrected=merged_content,
                correction_delta=delta
            )
            await db.correction_patterns.insert_one(pattern.dict())
            logger.info(f"Stored correction pattern for {doc_path} (repo {repo_key})")

        except Exception as e:
            logger.warning(f"Feedback processing failed for {doc_path}: {e}")