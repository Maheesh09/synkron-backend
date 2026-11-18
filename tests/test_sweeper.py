from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import sweeper

NOW = datetime(2026, 11, 18, 12, 0, 0)


def _matches(filt: dict, doc: dict) -> bool:
    """Tiny evaluator for the operators the sweeper uses ($or, $lt, $exists)."""
    for key, cond in filt.items():
        if key == "$or":
            if not any(_matches(f, doc) for f in cond):
                return False
        elif isinstance(cond, dict):
            if "$exists" in cond and (key in doc) != cond["$exists"]:
                return False
            if "$lt" in cond and not (key in doc and doc[key] < cond["$lt"]):
                return False
        elif doc.get(key) != cond:
            return False
    return True


@pytest.fixture
def fake_db(monkeypatch):
    db = MagicMock()
    db.pipeline_runs.update_many = AsyncMock(return_value=MagicMock(modified_count=2))
    monkeypatch.setattr(sweeper, "get_db", lambda: db)
    return db


@pytest.mark.asyncio
async def test_sweeper_marks_only_runs_stalled_for_over_15_minutes(fake_db):
    count = await sweeper.sweep_abandoned_runs(now=NOW)
    assert count == 2

    filt, update = fake_db.pipeline_runs.update_many.await_args.args
    old, recent = NOW - timedelta(minutes=16), NOW - timedelta(minutes=5)

    # Stalled: running, last attempt long ago.
    assert _matches(filt, {"status": "running", "last_attempt_at": old})
    # Legacy run without last_attempt_at falls back to created_at.
    assert _matches(filt, {"status": "running", "created_at": old})
    # Still in progress / retrying recently: leave alone.
    assert not _matches(filt, {"status": "running", "last_attempt_at": recent, "created_at": old})
    assert not _matches(filt, {"status": "running", "created_at": recent})
    # Finished runs are never touched.
    assert not _matches(filt, {"status": "completed", "last_attempt_at": old})

    assert update["$set"]["status"] == "failed"
    assert update["$set"]["error_type"] == "Abandoned"


def test_sweep_endpoint_requires_internal_token(monkeypatch, fake_db):
    from app.main import app
    monkeypatch.setattr(settings, "INTERNAL_SECRET", "s3cret")
    client = TestClient(app)
    assert client.post("/internal/sweep").status_code == 403
    r = client.post("/internal/sweep", headers={"X-Internal-Token": "s3cret"})
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "abandoned": 2}
