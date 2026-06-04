import httpx
import base64
from urllib.parse import quote
from app.config import settings
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# GitLab REST API v4 — the real, stable API. (Class kept named GitLabMCP so the
# rest of the codebase doesn't need to change.)
API_BASE = "https://gitlab.com/api/v4"

# Default branch of the target repos. Change to "master" if your repo uses it.
DEFAULT_BRANCH = "main"


class GitLabMCP:
    """
    GitLab client wrapping the operations the Synkron agents need.
    Talks to GitLab REST API v4 directly using a Personal Access Token.
    """

    def __init__(self):
        # PATs authenticate via the PRIVATE-TOKEN header on REST v4.
        self.headers = {"PRIVATE-TOKEN": settings.GITLAB_PAT}

    async def _get(self, path: str, params: dict = None) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(f"{API_BASE}{path}", headers=self.headers, params=params)
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str, json_body: dict = None, params: dict = None) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{API_BASE}{path}", headers=self.headers, json=json_body, params=params
            )
            r.raise_for_status()
            return r.json()

    # ── Read operations ────────────────────────────────────────────────

    async def get_commit_diff(self, project_id: int, sha: str) -> str:
        """
        Build a unified-diff-style string for a commit.
        REST returns one object per changed file; we stitch them together with a
        `diff --git` header so the Code Analyzer's file filter still works.
        """
        diffs = await self._get(
            f"/projects/{project_id}/repository/commits/{sha}/diff"
        )
        parts = []
        for f in diffs:
            old = f.get("old_path") or f.get("new_path")
            new = f.get("new_path") or old
            parts.append(f"diff --git a/{old} b/{new}\n{f.get('diff', '')}")
        return "\n".join(parts)

    async def list_repository_tree(
        self, project_id: int, ref: str = DEFAULT_BRANCH
    ) -> List[Dict]:
        """List all files recursively, handling pagination."""
        items, page = [], 1
        while True:
            batch = await self._get(
                f"/projects/{project_id}/repository/tree",
                params={
                    "ref": ref,
                    "recursive": "true",
                    "per_page": 100,
                    "page": page,
                },
            )
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items

    async def get_file_content(
        self, project_id: int, path: str, ref: str = DEFAULT_BRANCH
    ) -> str:
        """Return decoded file content. The file path must be URL-encoded."""
        enc_path = quote(path, safe="")
        data = await self._get(
            f"/projects/{project_id}/repository/files/{enc_path}",
            params={"ref": ref},
        )
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    # ── Write operations ───────────────────────────────────────────────

    async def create_branch(
        self, project_id: int, branch: str, ref: str = DEFAULT_BRANCH
    ):
        await self._post(
            f"/projects/{project_id}/repository/branches",
            params={"branch": branch, "ref": ref},
        )

    async def commit_file(
        self,
        project_id: int,
        branch: str,
        file_path: str,
        content: str,
        message: str,
    ):
        """
        Commit a single file update via the commits API. Author is synkron-bot.
        Uses action 'update' (docs being rewritten already exist). If you ever
        need to create new files, switch the action to 'create'.
        """
        await self._post(
            f"/projects/{project_id}/repository/commits",
            json_body={
                "branch": branch,
                "commit_message": message,
                "author_name": "synkron-bot",
                "author_email": "bot@synkron.dev",
                "actions": [
                    {"action": "update", "file_path": file_path, "content": content}
                ],
            },
        )

    async def create_merge_request(
        self, project_id: int, source_branch: str, title: str, description: str
    ) -> Dict:
        """Open an MR into the default branch and return its metadata (incl. web_url)."""
        return await self._post(
            f"/projects/{project_id}/merge_requests",
            json_body={
                "source_branch": source_branch,
                "target_branch": DEFAULT_BRANCH,
                "title": title,
                "description": description,
                "labels": "documentation,synkron",
            },
        )