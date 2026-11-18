from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents import doc_writer


@pytest.mark.asyncio
async def test_correction_lookup_queries_by_repo_key_and_doc_type(monkeypatch):
    cursor = MagicMock()
    cursor.sort.return_value.limit.return_value.to_list = AsyncMock(return_value=[])
    db = MagicMock()
    db.correction_patterns.find.return_value = cursor
    monkeypatch.setattr(doc_writer, "get_db", lambda: db)
    monkeypatch.setattr(doc_writer, "call_gemini", AsyncMock(return_value="new text"))

    client = MagicMock(owner="acme", repo="widgets")
    client.get_file_content = AsyncMock(return_value="old text")
    agent = doc_writer.DocWriterAgent(
        client, impact={"affected_docs": []}, analysis={"summary": "x", "changes": []})

    await agent._rewrite_doc({"path": "docs/deploy.md"})

    query = db.correction_patterns.find.call_args.args[0]
    # repo_id is stored as an int, so comparing it to "owner/repo" never matches;
    # query on the string key only, which the index covers.
    assert query == {"repo_key": "acme/widgets", "doc_type": "deployment"}
