from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers import dashboard


def _agg(result):
    m = MagicMock()
    m.to_list = AsyncMock(return_value=result)
    return m


@pytest.fixture
def db(monkeypatch):
    counts = {None: 10, "completed": 6, "skipped": 3, "failed": 1}
    db = MagicMock()
    db.pipeline_runs.count_documents = AsyncMock(
        side_effect=lambda q: counts[q.get("status")])
    db.pipeline_runs.aggregate = MagicMock(side_effect=[
        _agg([{"avg": 12.0}]), _agg([{"total": 4}]),
        _agg([{"durations": [10.0, 12.0, 14.0], "cost": 0.5, "tokens": 900}]),
    ])
    monkeypatch.setattr(dashboard, "get_db", lambda: db)
    monkeypatch.setattr(dashboard, "_user_repo_ids", AsyncMock(return_value=[1, 2]))
    return db


@pytest.mark.asyncio
async def test_success_rate_excludes_skipped_runs(db):
    """Same definition as the dashboard: completed / (completed + failed)."""
    h = await dashboard.get_health_stats(repo_id=None, github_id=7)
    assert h["failed_runs"] == 1
    assert h["success_rate"] == round(6 / 7 * 100, 1)     # not 6/10


@pytest.mark.asyncio
async def test_health_can_be_scoped_to_one_owned_repo(db):
    await dashboard.get_health_stats(repo_id=2, github_id=7)
    scope = db.pipeline_runs.count_documents.await_args_list[0].args[0]
    assert scope["repo_id"] == {"$in": [2]}


@pytest.mark.asyncio
async def test_health_for_a_repo_the_user_does_not_own_is_404(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        await dashboard.get_health_stats(repo_id=99, github_id=7)
    assert e.value.status_code == 404
