from app.services.gitlab_mcp import GitLabMCP
from app.database import get_db
from app.models.pipeline_run import CorrectionPattern
import difflib, logging

logger = logging.getLogger(__name__)


async def process_feedback(payload: dict):
    db         = get_db()
    mcp        = GitLabMCP()
    project_id = payload["project"]["id"]
    mr_id      = payload["object_attributes"]["iid"]

    # Find the pipeline run linked to this merged MR
    run = await db.pipeline_runs.find_one({"mr_id": mr_id, "repo_id": project_id})
    if not run:
        return

    for doc_path in run.get("docs_updated", []):
        try:
            # Get what was merged (human-edited version)
            merged_content = await mcp.get_file_content(project_id, doc_path)

            # Get what Synkron originally wrote
            run_detail = await db.pipeline_run_details.find_one(
                {"run_id": run["run_id"], "doc_path": doc_path}
            )
            if not run_detail:
                continue

            ai_content = run_detail["ai_written"]

            # If no edits, developer accepted Synkron's output — great!
            if ai_content.strip() == merged_content.strip():
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
            pattern = CorrectionPattern(
                repo_id=project_id, mr_id=mr_id,
                doc_path=doc_path, doc_type=doc_type,
                ai_written=ai_content,
                human_corrected=merged_content,
                correction_delta=delta
            )
            await db.correction_patterns.insert_one(pattern.dict())
            logger.info(f"Stored correction pattern for {doc_path} (repo {project_id})")

        except Exception as e:
            logger.warning(f"Feedback processing failed for {doc_path}: {e}")