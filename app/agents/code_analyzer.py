from app.services.github import GitHubClient 
from app.services.gemini import call_gemini
import json, logging

logger = logging.getLogger(__name__)

_LOCK_OR_BINARY = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".lock", ".pyc")
_EXACT_SKIP     = ("package-lock.json", "yarn.lock", "poetry.lock")
_DOC_EXTENSIONS = (".md", ".rst", ".mdx", ".txt")


class CodeAnalyzerAgent:
    def __init__(self, client: GitHubClient, before_sha: str, after_sha: str):
        self.client     = client
        self.before_sha = before_sha
        self.after_sha  = after_sha

    async def run(self) -> dict:
        raw_diff = await self.client.get_push_diff(self.before_sha, self.after_sha)
        filtered = self._filter_diff(raw_diff)

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
                path = line.split(" b/")[-1].strip()        
                name = path.rsplit("/", 1)[-1]
                skip = self._should_skip(name)
            if not skip:
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _should_skip(name: str) -> bool:
        if name in _EXACT_SKIP:                 return True
        if name.endswith(_LOCK_OR_BINARY):      return True
        if name.endswith(_DOC_EXTENSIONS):      return True
        if "__pycache__" in name:               return True
        stem = name.rsplit(".", 1)[0]

        
        if stem.startswith("test_") or stem.endswith("_test"):  return True
        if ".spec." in name or ".test." in name:                return True
        return False