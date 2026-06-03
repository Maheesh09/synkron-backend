from app.services.gitlab_mcp import GitLabMCP
from app.services.gemini import call_gemini
import json, logging

logger = logging.getLogger(__name__)

SKIP_PATTERNS = [
    "package-lock.json", "yarn.lock", "poetry.lock",
    "__pycache__", ".pyc", "test_", "_test.", ".spec.",
    ".png", ".jpg", ".gif", ".svg", ".ico", ".lock"
]


class CodeAnalyzerAgent:
    def __init__(self, repo_id: int, commit_sha: str):
        self.repo_id    = repo_id
        self.commit_sha = commit_sha
        self.mcp        = GitLabMCP()

    async def run(self) -> dict:
        raw_diff = await self.mcp.get_commit_diff(self.repo_id, self.commit_sha)
        filtered  = self._filter_diff(raw_diff)

        if not filtered.strip():
            return {"summary": "no relevant changes", "changes": [], "doc_hints": []}

        prompt = f"""Analyze this code commit diff and return ONLY valid JSON.

DIFF:
{filtered[:6000]}

Return this exact JSON structure:
{{
  "summary": "one clear sentence what changed",
  "changes": [
    {{
      "file": "path/to/file",
      "change_type": "feature_added|bug_fix|refactor|api_change|config_change|removed",
      "semantic_meaning": "plain English: what behavior changed for users or developers"
    }}
  ],
  "doc_hints": ["keyword1", "keyword2", "keyword3"]
}}

doc_hints must be words/phrases a developer would find in documentation.
If this is a pure internal refactor with no behavior change, return empty doc_hints [].
Return ONLY the JSON object, no markdown, no explanation."""

        raw = await call_gemini(prompt, model="flash", temperature=0.1)
        try:
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except json.JSONDecodeError:
            logger.warning("JSON parse failed, returning empty")
            return {"summary": "parse error", "changes": [], "doc_hints": []}

    def _filter_diff(self, diff: str) -> str:
        lines, skip = [], False
        for line in diff.split("\n"):
            if line.startswith("diff --git"):
                skip = any(p in line for p in SKIP_PATTERNS)
            if not skip:
                lines.append(line)
        return "\n".join(lines)