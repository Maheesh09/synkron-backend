import base64
import logging

from urllib.parse import quote

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
        escaped_branch = quote(branch, safe="/")
        resp = await self._request("GET", f"{self._repo_path}/git/ref/heads/{escaped_branch}")
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

    async def commit_files(self, branch: str, files: dict[str, str], message: str) -> str:
        """
        Commit multiple files to `branch` in a single atomic commit via the
        git data API:
          1. read the branch head commit and its tree
          2. build a NEW tree layered on the old one, one entry per changed file
          3. create a commit whose parent is the old head
          4. move the branch ref to the new commit

        No author/committer is set, so GitHub attributes the commit to the App
        itself — it appears as `synkron[bot]`. Returns the new commit SHA.
        """
        head_sha = await self.get_branch_head(branch)
        head_commit = (await self._request(
            "GET", f"{self._repo_path}/git/commits/{head_sha}"
        )).json()
        base_tree_sha = head_commit["tree"]["sha"]

        # Fetch the base tree to look up existing modes for paths
        base_tree_resp = (await self._request(
            "GET",
            f"{self._repo_path}/git/trees/{base_tree_sha}",
            params={"recursive": "1"}
        )).json()

        # Build a map of path -> (mode, type) from the base tree
        existing_entries = {
            entry["path"]: (entry["mode"], entry["type"])
            for entry in base_tree_resp.get("tree", [])
        }

        tree_entries = []
        for path, content in files.items():
            # Determine mode: reuse existing mode if present, default to "100644" for new files
            if path in existing_entries:
                mode, entry_type = existing_entries[path]
                # Reject if the entry is a tree or submodule (not a blob)
                if entry_type != "blob":
                    raise ValueError(
                        f"Cannot commit content to path '{path}': "
                        f"it is a '{entry_type}' (tree/submodule), not a blob. "
                        "This method only supports committing blob content."
                    )
            else:
                mode = "100644"  # Default mode for new regular files

            tree_entries.append({
                "path": path,
                "mode": mode,
                "type": "blob",
                "content": content
            })

        new_tree = (await self._request(
            "POST",
            f"{self._repo_path}/git/trees",
            json={"base_tree": base_tree_sha, "tree": tree_entries},
        )).json()

        new_commit = (await self._request(
            "POST",
            f"{self._repo_path}/git/commits",
            json={"message": message, "tree": new_tree["sha"], "parents": [head_sha]},
        )).json()

        escaped_branch = quote(branch, safe="/")
        await self._request(
            "PATCH",
            f"{self._repo_path}/git/refs/heads/{escaped_branch}",
            json={"sha": new_commit["sha"]},
        )
        return new_commit["sha"]