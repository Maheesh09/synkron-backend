import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.agents import orchestrator
from app.config import settings
from app.services.errors import PipelineRetry, is_retryable
from app.services.gemini import GeminiTruncatedError, TransientGeminiError


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://api.github.com/x")
    return httpx.HTTPStatusError("err", request=req, response=httpx.Response(status, request=req))


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    TransientGeminiError("empty"),
    asyncio.TimeoutError(),
    httpx.ReadTimeout("slow"),
    httpx.ConnectError("down"),
    _http_error(502),
    _http_error(429),
    ServerSelectionTimeoutError("mongo"),
])
def test_retryable_errors(exc):
    assert is_retryable(exc)


@pytest.mark.parametrize("exc", [
    GeminiTruncatedError("too long"),
    _http_error(404),
    _http_error(422),
    ValueError("bad payload"),
    KeyError("summary"),
])
def test_permanent_errors(exc):
    assert not is_retryable(exc)


# --------------------------------------------------------------------------
# Orchestrator behaviour
# --------------------------------------------------------------------------

def _payload():
    return {"repository": {"id": 1, "name": "w", "full_name": "acme/w"},
            "installation": {"id": 9}}


@pytest.fixture
def fake_db(monkeypatch):
    db = MagicMock()
    db.pipeline_runs.find_one = AsyncMock(return_value=None)
    db.pipeline_runs.insert_one = AsyncMock()
    db.pipeline_runs.update_one = AsyncMock()
    db.repositories.update_one = AsyncMock()
    monkeypatch.setattr(orchestrator, "get_db", lambda: db)
    return db


def _statuses_set(db):
    return [c.args[1].get("$set", {}).get("status") for c in db.pipeline_runs.update_one.await_args_list]


@pytest.mark.asyncio
async def test_transient_error_asks_for_retry_and_keeps_run_open(fake_db, monkeypatch):
    monkeypatch.setattr(orchestrator, "_run_direct_agents",
                        AsyncMock(side_effect=TransientGeminiError("503")))
    with pytest.raises(PipelineRetry):
        await orchestrator.run_pipeline("a", "b", 1, _payload(), final_attempt=False)
    assert "failed" not in _statuses_set(fake_db)


@pytest.mark.asyncio
async def test_permanent_error_marks_run_failed_without_retry(fake_db, monkeypatch):
    monkeypatch.setattr(orchestrator, "_run_direct_agents",
                        AsyncMock(side_effect=GeminiTruncatedError("cut")))
    result = await orchestrator.run_pipeline("a", "b", 1, _payload(), final_attempt=False)
    assert result["status"] == "failed"
    assert "failed" in _statuses_set(fake_db)


@pytest.mark.asyncio
async def test_transient_error_on_final_attempt_marks_run_failed(fake_db, monkeypatch):
    monkeypatch.setattr(orchestrator, "_run_direct_agents",
                        AsyncMock(side_effect=TransientGeminiError("503")))
    result = await orchestrator.run_pipeline("a", "b", 1, _payload(), final_attempt=True)
    assert result["status"] == "failed"
    assert "failed" in _statuses_set(fake_db)


@pytest.mark.asyncio
async def test_retry_reuses_the_run_for_the_same_task(fake_db, monkeypatch):
    fake_db.pipeline_runs.find_one = AsyncMock(return_value={"run_id": "run-1"})
    agents = AsyncMock(return_value={"status": "skipped", "stage_ms": {}})
    monkeypatch.setattr(orchestrator, "_run_direct_agents", agents)

    await orchestrator.run_pipeline("a", "b", 1, _payload(), task_name="projects/p/tasks/gh-1")

    fake_db.pipeline_runs.insert_one.assert_not_called()
    assert agents.await_args.args[0] == "run-1"


# --------------------------------------------------------------------------
# HTTP contract with Cloud Tasks
# --------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings, "INTERNAL_SECRET", "s3cret")
    monkeypatch.setattr(settings, "PIPELINE_MAX_ATTEMPTS", 3)
    return TestClient(app)


_BODY = {"after": "b" * 40, "before": "a" * 40,
         "repository": {"id": 1, "name": "w", "full_name": "acme/w"},
         "installation": {"id": 9}}


def test_endpoint_returns_503_for_retryable(client, monkeypatch):
    from app.routers import pipeline
    run = AsyncMock(side_effect=PipelineRetry(TransientGeminiError("x")))
    monkeypatch.setattr(pipeline, "run_pipeline", run)
    r = client.post("/internal/run-pipeline", json=_BODY,
                    headers={"X-Internal-Token": "s3cret", "X-CloudTasks-TaskRetryCount": "0",
                             "X-CloudTasks-TaskName": "gh-1"})
    assert r.status_code == 503
    assert run.await_args.kwargs["final_attempt"] is False
    assert run.await_args.kwargs["task_name"] == "gh-1"


def test_endpoint_returns_200_for_permanent_failure(client, monkeypatch):
    from app.routers import pipeline
    monkeypatch.setattr(pipeline, "run_pipeline",
                        AsyncMock(return_value={"status": "failed", "mr_url": None}))
    r = client.post("/internal/run-pipeline", json=_BODY,
                    headers={"X-Internal-Token": "s3cret", "X-CloudTasks-TaskRetryCount": "2"})
    assert r.status_code == 200
    assert r.json()["status"] == "failed"


def test_endpoint_flags_last_attempt(client, monkeypatch):
    from app.routers import pipeline
    run = AsyncMock(return_value={"status": "completed"})
    monkeypatch.setattr(pipeline, "run_pipeline", run)
    client.post("/internal/run-pipeline", json=_BODY,
                headers={"X-Internal-Token": "s3cret", "X-CloudTasks-TaskRetryCount": "2"})
    assert run.await_args.kwargs["final_attempt"] is True


# --------------------------------------------------------------------------
# One run per Cloud Tasks task
# --------------------------------------------------------------------------

def test_task_name_has_a_unique_index_that_ignores_runs_without_one():
    from app.database import index_specs
    db = MagicMock()
    specs = [(c, k, o) for c, k, o in index_specs(db) if c is db.pipeline_runs]
    keys = {tuple(k): o for _, k, o in specs}
    opts = keys[(("task_name", 1),)]
    assert opts["unique"] is True
    # Partial, not sparse: a sparse index still indexes explicit nulls.
    assert opts["partialFilterExpression"] == {"task_name": {"$type": "string"}}


@pytest.mark.asyncio
async def test_run_without_task_name_does_not_store_a_null_task_name(fake_db):
    await orchestrator._start_run(fake_db, 1, "b", None)
    doc = fake_db.pipeline_runs.insert_one.await_args.args[0]
    assert "task_name" not in doc


@pytest.mark.asyncio
async def test_overlapping_attempts_share_one_run(fake_db):
    """If another attempt inserted the run between our find and insert, the
    unique index rejects ours and we join the existing run instead."""
    from pymongo.errors import DuplicateKeyError
    fake_db.pipeline_runs.find_one = AsyncMock(side_effect=[None, {"run_id": "run-1"}])
    fake_db.pipeline_runs.insert_one = AsyncMock(side_effect=DuplicateKeyError("dup"))
    assert await orchestrator._start_run(fake_db, 1, "b", "projects/p/tasks/gh-1") == "run-1"
