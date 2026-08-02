import base64
import logging

import httpx

from app.services.github_auth import get_installation_token, API_BASE, API_VERSION

logger = logging.getLogger(__name__)

_ACCEPT_JSON = "application/vnd.github+json"
_ACCEPT_DIFF = "application/vnd.github.diff"


class GitHubClient:
    def __init__(self, installation_id: int, owner: str, repo: str, default_branch: str = "main"):
        self.installation_id = installation_id
        self.owner = owner
        self.repo = repo
        self.default_branch = default_branch

    @property
    def _repo_path(self) -> str:
        return f"/repos/{self.owner}/{self.repo}"

    async def _headers(self, accept: str = _ACCEPT_JSON) -> dict:
        token = await get_installation_token(self.installation_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "X-GitHub-Api-Version": API_VERSION,
        }

    async def _request(self, method: str, path: str, *, accept: str = _ACCEPT_JSON, **kwargs) -> httpx.Response:
        headers = await self._headers(accept)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)
            resp.raise_for_status()
            return resp

    async def get_push_diff(self, before_sha: str, after_sha: str) -> str:
        """
        Unified diff for a push. Uses the raw-diff media type, so the result
        already contains `diff --git a/… b/…` headers — the exact shape the
        Code Analyzer's filter expects, no reconstruction needed.

        On the first push to a new branch, `before` is all zeros; GitHub can't
        compare against that, so we fall back to the single commit's diff.
        """
        if not before_sha or set(before_sha) == {"0"}:
            resp = await self._request(
                "GET", f"{self._repo_path}/commits/{after_sha}", accept=_ACCEPT_DIFF
            )
            return resp.text
        resp = await self._request(
            "GET",
            f"{self._repo_path}/compare/{before_sha}...{after_sha}",
            accept=_ACCEPT_DIFF,
        )
        return resp.text    