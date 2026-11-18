from app.services.github import GitHubClient
from app.services.gemini import call_gemini
import json, logging, re

logger = logging.getLogger(__name__)

_LOCK_OR_BINARY = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".lock", ".pyc")
_EXACT_SKIP     = ("package-lock.json", "yarn.lock", "poetry.lock")
_DOC_EXTENSIONS = (".md", ".rst", ".mdx", ".txt")

# Characters of diff sent to the analyzer. Whole files are packed in priority
# order up to this budget; the rest are listed by name so the model knows.
DIFF_BUDGET = 12_000

# Lower rank = more likely to change what users/developers see in the docs.
_PRIORITY = (
    (0, re.compile(r"(^|/)(routes?|routers?|api|endpoints?|controllers?|views?|handlers?)(/|\.|_|$)")),
    (1, re.compile(r"(^|/)(models?|schemas?|types?|payloads?|entities)(/|\.|_|$)")),
    (2, re.compile(r"(^|/)(config|settings|\.env|dockerfile|.*\.(ya?ml|toml|ini))")),
)


def _rank(path: str) -> int:
    p = path.lower()
    for rank, pattern in _PRIORITY:
        if pattern.search(p):
            return rank
    return 3


def _split_sections(diff: str) -> list[tuple[str, str]]:
    """[(path, section_text)] for each `diff --git` block, in original order."""
    sections, current, path = [], [], ""
    for line in diff.split("\n"):
        if line.startswith("diff --git"):
            if current:
                sections.append((path, "\n".join(current)))
            current, path = [line], line.split(" b/")[-1].strip()
        elif current:
            current.append(line)
    if current:
        sections.append((path, "\n".join(current)))
    return sections


def pack_diff(diff: str, budget: int = DIFF_BUDGET) -> str:
    """
    Fit a diff into `budget` characters without cutting a file in half:
    rank files (routes/API, then models, then config, then the rest), add whole
    sections while they fit, and list the files left out. A single file larger
    than the whole budget is cut on a line boundary rather than dropped.
    """
    if len(diff) <= budget:
        return diff
    sections = _split_sections(diff)
    ordered = sorted(enumerate(sections), key=lambda t: (_rank(t[1][0]), t[0]))

    kept, omitted, used = [], [], 0
    for _, (path, text) in ordered:
        if used + len(text) + 1 <= budget:
            kept.append(text)
            used += len(text) + 1
        else:
            omitted.append(path)

    if not kept and ordered:
        path, text = ordered[0][1]
        cut = text[:budget].rsplit("\n", 1)[0]
        kept.append(f"{cut}\n[{path}: remainder of this file not shown]")
        omitted.remove(path)

    out = "\n".join(kept)
    if omitted:
        out += "\n\n[Diff budget reached. Changed files not shown: " + ", ".join(omitted) + "]"
    return out


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
{pack_diff(filtered)}

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
