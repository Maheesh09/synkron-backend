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
        compare against that, so we compare against the default branch instead.
        """
        if not before_sha or set(before_sha) == {"0"}:
            resp = await self._request(
                "GET",
                f"{self._repo_path}/compare/{self.default_branch}...{after_sha}",
                accept=_ACCEPT_DIFF,
            )
            return resp.text
        resp = await self._request(
            "GET",
            f"{self._repo_path}/compare/{before_sha}...{after_sha}",
            accept=_ACCEPT_DIFF,
        )
        return resp.text    

    async def list_tree(self, ref: str | None = None) -> list[dict]:
        """
        List every file in the repo at `ref` (default branch if omitted).

        GitHub tree entries only carry `path`; the Impact Mapper expects `name`
        too. We normalise each entry to {name, path, type} and keep only blobs
        (files, not directories), so that agent stays unchanged.
        """
        ref = ref or self.default_branch
        resp = await self._request(
            "GET", f"{self._repo_path}/git/trees/{ref}", params={"recursive": "1"}
        )
        data = resp.json()
        if data.get("truncated"):
            raise RuntimeError(
                f"Repository tree for {self.owner}/{self.repo} at ref '{ref}' was truncated by GitHub. "
                "The repository is too large to retrieve the complete file list."
            )
        return [
            {"name": e["path"].rsplit("/", 1)[-1], "path": e["path"], "type": e["type"]}
            for e in data.get("tree", [])
            if e.get("type") == "blob"
        ]


    async def get_file_content(self, path: str, ref: str | None = None) -> str:
        """
        Return a text file's decoded content at `ref`.

        The contents API returns base64. Files over ~1 MB come back with empty
        content, so for those we fetch the raw content directly using the raw
        media type, which is capped at 100 MB.
        """
        ref = ref or self.default_branch
        resp = await self._request(
            "GET", f"{self._repo_path}/contents/{path}", params={"ref": ref}
        )
        data = resp.json()
        if data.get("encoding") == "base64" and data.get("content"):
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        # For large files, fetch raw content directly
        raw_resp = await self._request(
            "GET",
            f"{self._repo_path}/contents/{path}",
            params={"ref": ref},
            accept="application/vnd.github.raw+json"
        )
        return raw_resp.text

    async def get_branch_head(self, branch: str) -> str:
        """Return the commit SHA a branch currently points at."""
        resp = await self._request("GET", f"{self._repo_path}/git/ref/heads/{branch}")
        return resp.json()["object"]["sha"]

    async def create_branch(self, new_branch: str, base: str | None = None) -> str:
        """
        Create a branch off `base` (default branch if omitted). Git has no
        'make a branch' primitive — a branch is just a ref pointing at a
        commit — so we resolve the base branch's head SHA first, then create a
        ref at it. Returns that base SHA.
        """
        base = base or self.default_branch
        base_sha = await self.get_branch_head(base)
        await self._request(
            "POST",
            f"{self._repo_path}/git/refs",
            json={"ref": f"refs/heads/{new_branch}", "sha": base_sha},
        )
        return base_sha