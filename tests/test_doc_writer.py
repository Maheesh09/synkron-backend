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


def _writer(monkeypatch, error):
    cursor = MagicMock()
    cursor.sort.return_value.limit.return_value.to_list = AsyncMock(return_value=[])
    db = MagicMock()
    db.correction_patterns.find.return_value = cursor
    monkeypatch.setattr(doc_writer, "get_db", lambda: db)
    monkeypatch.setattr(doc_writer, "call_gemini", AsyncMock(side_effect=error))
    client = MagicMock(owner="acme", repo="widgets")
    client.get_file_content = AsyncMock(return_value="old text")
    impact = {"affected_docs": [{"path": "docs/a.md"}, {"path": "docs/b.md"}]}
    return doc_writer.DocWriterAgent(client, impact, {"summary": "x", "changes": []})


@pytest.mark.asyncio
async def test_retryable_error_propagates_instead_of_skipping_the_doc(monkeypatch):
    from app.services.gemini import TransientGeminiError
    with pytest.raises(TransientGeminiError):
        await _writer(monkeypatch, TransientGeminiError("503")).run()


@pytest.mark.asyncio
async def test_permanent_error_skips_only_that_doc(monkeypatch):
    from app.services.gemini import GeminiTruncatedError
    assert await _writer(monkeypatch, GeminiTruncatedError("cut")).run() == []


@pytest.mark.asyncio
async def test_gemini_503_during_doc_writing_makes_the_run_ask_for_retry(monkeypatch):
    """End to end through the orchestrator: no silent 'no_doc_updates' skip."""
    from app.agents import orchestrator
    from app.services.errors import PipelineRetry
    from app.services.gemini import TransientGeminiError

    writer = _writer(monkeypatch, TransientGeminiError("503"))
    monkeypatch.setattr(orchestrator, "DocWriterAgent", lambda *a: writer)
    monkeypatch.setattr(orchestrator, "GitHubClient", MagicMock())
    monkeypatch.setattr(orchestrator, "CodeAnalyzerAgent", lambda *a: MagicMock(
        run=AsyncMock(return_value={"summary": "x", "changes": [], "doc_hints": ["auth"]})))
    monkeypatch.setattr(orchestrator, "ImpactMapperAgent", lambda *a: MagicMock(
        run=AsyncMock(return_value={"affected_docs": [{"path": "docs/a.md"}]})))
    db = MagicMock()
    db.pipeline_runs.find_one = AsyncMock(return_value=None)
    db.pipeline_runs.insert_one = AsyncMock()
    db.pipeline_runs.update_one = AsyncMock()
    db.repositories.update_one = AsyncMock()
    monkeypatch.setattr(orchestrator, "get_db", lambda: db)

    payload = {"repository": {"id": 1, "full_name": "acme/widgets"}, "installation": {"id": 9}}
    with pytest.raises(PipelineRetry):
        await orchestrator.run_pipeline("a", "b", 1, payload, final_attempt=False)
