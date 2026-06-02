from google.adk.tools import FunctionTool
from app.services.gitlab_mcp import GitLabMCP
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Shared MCP client instance
_mcp = GitLabMCP()



# Each function below is wrapped into an ADK FunctionTool.
# The docstring becomes the tool's description visible to the Gemini model.



async def get_commit_diff(project_id: int, sha: str) -> str:
    """
    Retrieves the complete unified diff for a given commit SHA.
    Use this first to understand what code changed in the push.

    Args:
        project_id: The GitLab project ID (integer).
        sha: The full commit SHA to retrieve the diff for.

    Returns:
        A string containing the unified diff with all changed files.
    """
    return await _mcp.get_commit_diff(project_id, sha)


async def list_repository_tree(project_id: int, ref: str = "main") -> List[Dict]:
    """
    Lists all files in the GitLab repository recursively.
    Use this to find which documentation files exist in the project.

    Args:
        project_id: The GitLab project ID (integer).
        ref: Branch or tag to list files from (default: "main").

    Returns:
        A list of file objects with name, path, and type fields.
    """
    return await _mcp.list_repository_tree(project_id, ref)


async def get_file_content(project_id: int, file_path: str) -> str:
    """
    Reads the current content of a file from the repository.
    Use this to read documentation files before rewriting them.

    Args:
        project_id: The GitLab project ID (integer).
        file_path: Path to the file relative to repo root (e.g., "docs/auth.md").

    Returns:
        The decoded file content as a string.
    """
    return await _mcp.get_file_content(project_id, file_path)


async def create_branch(project_id: int, branch_name: str, ref: str = "main") -> Dict:
    """
    Creates a new branch in the GitLab repository.
    Always create a branch before committing documentation changes.

    Args:
        project_id: The GitLab project ID (integer).
        branch_name: Name for the new branch (e.g., "synkron/docs-abc123de").
        ref: Base branch to create from (default: "main").

    Returns:
        A dict with branch creation status.
    """
    await _mcp.create_branch(project_id, branch_name, ref)
    return {"status": "created", "branch": branch_name}


async def commit_file(
    project_id: int,
    branch_name: str,
    file_path: str,
    content: str,
    commit_message: str
) -> Dict:
    """
    Commits an updated file to a branch in the GitLab repository.
    Use after rewriting a documentation file to save the changes.

    Args:
        project_id: The GitLab project ID (integer).
        branch_name: The branch to commit to.
        file_path: Path to the file to update (e.g., "docs/auth.md").
        content: The complete new file content to commit.
        commit_message: A descriptive commit message.

    Returns:
        A dict with commit status and short SHA.
    """
    await _mcp.commit_file(project_id, branch_name, file_path, content, commit_message)
    return {"status": "committed", "path": file_path}


async def create_merge_request(
    project_id: int,
    source_branch: str,
    title: str,
    description: str
) -> Dict:
    """
    Opens a merge request on GitLab from the source branch to main.
    Call this last, after all documentation files have been committed.

    Args:
        project_id: The GitLab project ID (integer).
        source_branch: The branch containing the doc updates.
        title: MR title. Start with "Docs: " then summarize what changed.
        description: Detailed markdown description of what was updated and why.

    Returns:
        A dict with web_url and iid (internal ID) of the created MR.
    """
    return await _mcp.create_merge_request(project_id, source_branch, title, description)


# ── Register all tools as ADK FunctionTool instances ──────────────────────
GITLAB_MCP_TOOLS = [
    FunctionTool(func=get_commit_diff),
    FunctionTool(func=list_repository_tree),
    FunctionTool(func=get_file_content),
    FunctionTool(func=create_branch),
    FunctionTool(func=commit_file),
    FunctionTool(func=create_merge_request),
]