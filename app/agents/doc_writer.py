from app.services.github import GitHubClient
from app.services.gemini import call_gemini
from app.database import get_db
from app.services.doc_types import classify_doc
from app.services.errors import is_retryable
from typing import List
import logging

logger = logging.getLogger(__name__)


class DocWriterAgent:
    def __init__(self, client: GitHubClient, impact: dict, analysis: dict):
        self.client   = client
        self.impact   = impact
        self.analysis = analysis

    async def run(self) -> List[dict]:
        updates = []
        for doc in self.impact["affected_docs"]:
            try:
                result = await self._rewrite_doc(doc)
            except Exception as e:
                # A Gemini 503 or timeout must reach the orchestrator's retry
                # logic; swallowing it would end the run as "no_doc_updates".
                if is_retryable(e):
                    raise
                logger.warning(f"Skipping {doc.get('path')}: {e}")
                continue
            if result:
                updates.append(result)
        return updates

    async def _rewrite_doc(self, doc: dict):
        current  = await self.client.get_file_content(doc["path"])
        doc_type = classify_doc(doc["path"])

        # Pull past correction examples from MongoDB (feedback loop), keyed by
        # the stable "owner/repo" string. Covered by the
        # (repo_key, doc_type, created_at) index created in database.py.
        repo_key = f"{self.client.owner}/{self.client.repo}"
        db       = get_db()
        examples = await db.correction_patterns.find(
            {"repo_key": repo_key, "doc_type": doc_type}
        ).sort("created_at", -1).limit(2).to_list(length=2)

        few_shot = ""
        if examples:
            ex_text  = "\n\n".join([
                f"BEFORE:\n{e['ai_written'][:500]}\nAFTER (human edited):\n{e['human_corrected'][:500]}"
                for e in examples
            ])
            few_shot = f"\n\nPast corrections by this team — match this style:\n{ex_text}"

        sections = ", ".join(doc.get("sections", []))
        prompt   = f"""You are a precise technical writer making a targeted documentation update.

CODE CHANGE: {self.analysis['summary']}
SEMANTIC MEANING: {[c['semantic_meaning'] for c in self.analysis.get('changes', [])]}

CURRENT DOCUMENTATION FILE:
---
{current}
---

TASK: Update ONLY these sections: {sections if sections else "any sections referencing the changed feature"}
- Do NOT change any other sections
- Maintain the exact same writing style, tone, and formatting as the original
- Keep the same heading structure and depth
- Return the COMPLETE updated file — all sections, unchanged ones included{few_shot}

Return ONLY the complete markdown file content. No explanation, no backticks."""

        updated = await call_gemini(prompt, model="pro", temperature=0.15, max_tokens=32768)

        if updated.strip() == current.strip():
            return None  # No actual changes — don't commit

        return {
            "doc_path":         doc["path"],
            "original_content": current,
            "updated_content":  updated,
            "sections_changed": doc.get("sections", []),
            "explanation":      doc.get("reason", ""),
            "doc_type":         doc_type
        }