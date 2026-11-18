from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import feedback


def _payload():
    return {
        "pull_request": {"number": 7},
        "repository": {"id": 42, "full_name": "acme/widgets", "default_branch": "main"},
        "installation": {"id": 99},
    }


@pytest.mark.asyncio
async def test_feedback_without_matching_run_returns_quietly(monkeypatch):
    db = MagicMock()
    db.pipeline_runs.find_one = AsyncMock(return_value=None)
    db.pipeline_runs.update_one = AsyncMock()
    monkeypatch.setattr(feedback, "get_db", lambda: db)

    await feedback.process_feedback(_payload())   # must not raise

    db.pipeline_runs.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_feedback_marks_matching_run_as_merged(monkeypatch):
    db = MagicMock()
    db.pipeline_runs.find_one = AsyncMock(
        return_value={"run_id": "run-1", "docs_updated": []})
    db.pipeline_runs.update_one = AsyncMock()
    monkeypatch.setattr(feedback, "get_db", lambda: db)
    monkeypatch.setattr(feedback, "GitHubClient", MagicMock())

    await feedback.process_feedback(_payload())

    db.pipeline_runs.update_one.assert_awaited_once()
    assert db.pipeline_runs.update_one.await_args.args[0] == {"run_id": "run-1"}
