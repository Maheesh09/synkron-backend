import asyncio

import pytest

from app.config import settings
from app.services import cloud_tasks


@pytest.mark.asyncio
async def test_local_pipeline_task_is_referenced_until_done(monkeypatch):
    """asyncio only holds weak references to tasks; an unreferenced one can be
    garbage-collected mid-run. The local path must keep a strong reference."""
    monkeypatch.setattr(settings, "LOCAL_DEV", True)
    release = asyncio.Event()

    async def fake_run_pipeline(**kwargs):
        await release.wait()

    from app.agents import orchestrator
    monkeypatch.setattr(orchestrator, "run_pipeline", fake_run_pipeline)

    await cloud_tasks.enqueue_pipeline({"repository": {"id": 1}, "after": "b"})
    assert len(cloud_tasks._background) == 1
    task = next(iter(cloud_tasks._background))

    release.set()
    await task
    await asyncio.sleep(0)          # let the done-callback run
    assert task not in cloud_tasks._background


@pytest.mark.asyncio
async def test_local_feedback_task_is_referenced(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_DEV", True)
    release = asyncio.Event()

    async def fake_feedback(payload):
        await release.wait()

    from app.services import feedback
    monkeypatch.setattr(feedback, "process_feedback", fake_feedback)

    await cloud_tasks.enqueue_feedback({})
    assert len(cloud_tasks._background) == 1
    release.set()
    await asyncio.gather(*cloud_tasks._background)
