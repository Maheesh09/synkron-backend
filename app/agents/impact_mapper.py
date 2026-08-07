from app.services.github import GitHubClient
from app.services.gemini import call_gemini
import json, asyncio, logging

logger = logging.getLogger(__name__)

DOC_EXTENSIONS      = (".md", ".rst", ".mdx", "openapi.yaml", "openapi.json")
RELEVANCE_THRESHOLD = 0.65
MAX_DOCS            = 12


class ImpactMapperAgent:
    def __init__(self, client: GitHubClient, analysis: dict):
        self.client   = client
        self.analysis = analysis

    async def run(self) -> dict:
        all_files = await self.client.list_repository_tree()

        # Filter to doc files only
        doc_files = [
            f for f in all_files
            if any(f["name"].endswith(e) or f["name"] == e for e in DOC_EXTENSIONS)
        ]

        # Prioritise the most likely-relevant docs BEFORE capping, so a repo
        # with >MAX_DOCS files doesn't lose the important one to tree order.
        hints = [h.lower() for h in self.analysis.get("doc_hints", [])]

        def _priority(f):
            p = f["path"].lower()
            score = 0
            if any(h in p for h in hints):                 score -= 3
            if "readme" in p:                              score -= 2
            if p.startswith("docs/") or "/docs/" in p:     score -= 1
            return (score, len(p))   # lower sorts first

        doc_files = sorted(doc_files, key=_priority)[:MAX_DOCS]

        if not doc_files:
            return {"affected_docs": []}

        # Read all doc files concurrently via GitHub API
        contents = await asyncio.gather(*[
            self.client.get_file_content(f["path"])
            for f in doc_files
        ], return_exceptions=True)

        # Build batch scoring prompt
        docs_text = "\n\n---\n\n".join([
            f"FILE {i}: {doc_files[i]['path']}\n{str(contents[i])[:1500]}"
            for i in range(len(doc_files))
            if not isinstance(contents[i], Exception)
        ])

        prompt = f"""A code change occurred: {self.analysis['summary']}
Key concepts: {", ".join(self.analysis.get("doc_hints", []))}

Documentation files in this repository:
{docs_text}

Score each file's relevance to this code change:
[
  {{
    "path": "file path",
    "score": 0.0-1.0,
    "sections": ["Section heading 1", "Section heading 2"],
    "reason": "one sentence why"
  }}
]

0.8+ = directly documents changed feature
0.5-0.8 = mentions related concepts
<0.5 = not relevant

Return ONLY the JSON array. No markdown."""

        raw = await call_gemini(prompt, model="flash", temperature=0.1)
        try:
            clean   = raw.replace("```json", "").replace("```", "").strip()
            scored  = json.loads(clean)
            affected = [d for d in scored if d["score"] >= RELEVANCE_THRESHOLD]
            return {"affected_docs": affected}
        except Exception:
            return {"affected_docs": []}