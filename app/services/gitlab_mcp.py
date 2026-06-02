import httpx
from app.config import settings
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# GitLab's official MCP server endpoint
MCP_BASE = "https://gitlab.com/api/mcp/v1"


class GitLabMCP:
    """
    Client for GitLab's Model Context Protocol (MCP) server.
    Wraps all Git operations that the Synkron agents need.
    """

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {settings.GITLAB_PAT}",
            "Content-Type": "application/json"
        }

    async def _call(self, tool: str, args: Dict) -> Any:
        """Make a single MCP tool call."""
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{MCP_BASE}/tools/call",
                headers=self.headers,
                json={"tool": tool, "arguments": args}
            )
            r.raise_for_status()
            return r.json()["result"]

    # ── Read operations ────────────────────────────────────────────────

    async def get_commit_diff(self, project_id: int, sha: str) -> str:
        """Get the raw unified diff for a commit."""
        result = await self._call("get_commit_diff", {
            "project_id": project_id,
            "sha": sha
        })
        return result["diff"]

    async def list_repository_tree(self, project_id: int, ref: str = "main") -> List[Dict]:
        """List all files in the repository recursively."""
        result = await self._call("list_repository_tree", {
            "project_id": project_id,
            "recursive": True,
            "ref": ref
        })
        return result

    async def get_file_content(self, project_id: int, path: str) -> str:
        """Get the decoded content of a file."""
        result = await self._call("get_file_content", {
            "project_id": project_id,
            "file_path": path
        })
        return result["content"]

    # ── Write operations ───────────────────────────────────────────────

    async def create_branch(self, project_id: int, branch: str, ref: str = "main"):
        """Create a new branch from a ref (usually main)."""
        await self._call("create_branch", {
            "project_id": project_id,
            "branch": branch,
            "ref": ref
        })

    async def commit_file(self, project_id: int, branch: str,
                          file_path: str, content: str, message: str):
        """Commit a file update. Author is always synkron-bot."""
        await self._call("commit_file", {
            "project_id": project_id,
            "branch": branch,
            "file_path": file_path,
            "content": content,
            "commit_message": message,
            "author_name": "synkron-bot",
            "author_email": "bot@synkron.dev"
        })

    async def create_merge_request(self, project_id: int, source_branch: str,
                                   title: str, description: str) -> Dict:
        """Open a merge request and return MR metadata including web_url."""
        return await self._call("create_merge_request", {
            "project_id": project_id,
            "source_branch": source_branch,
            "target_branch": "main",
            "title": title,
            "description": description,
            "labels": ["documentation", "synkron"]
        })