from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.services import rate_limit

HOUR = 3600
T_10_59_59 = 1_700_000_000 - (1_700_000_000 % HOUR) + HOUR - 1
T_11_00_01 = T_10_59_59 + 2


@pytest.fixture
def coll(monkeypatch):
    """Fake rate_limits collection that tracks counts per bucket key."""
    counts: dict[str, int] = {}

    async def find_one_and_update(filt, update, **kw):
        key = filt["_id"]
        counts[key] = counts.get(key, 0) + update["$inc"]["count"]
        return {"_id": key, "count": counts[key]}

    async def update_one(filt, update, **kw):
        key = filt["_id"]
        counts[key] = counts.get(key, 0) + update["$inc"]["count"]

    c = MagicMock()
    c.find_one_and_update = AsyncMock(side_effect=find_one_and_update)
    c.update_one = AsyncMock(side_effect=update_one)
    c.counts = counts
    db = MagicMock(rate_limits=c)
    monkeypatch.setattr(rate_limit, "get_db", lambda: db)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_HOUR", 2)
    return c


@pytest.mark.asyncio
async def test_release_hits_the_bucket_that_was_reserved(coll, monkeypatch):
    monkeypatch.setattr(rate_limit.time, "time", lambda: T_10_59_59)
    ok, key = await rate_limit.reserve_rate_limit_quota(7)
    assert ok and key

    monkeypatch.setattr(rate_limit.time, "time", lambda: T_11_00_01)
    await rate_limit.release_rate_limit_quota(key)

    assert coll.counts == {key: 0}     # 10:00 bucket back to zero, 11:00 untouched


@pytest.mark.asyncio
async def test_rejected_reservation_does_not_leave_the_counter_inflated(coll, monkeypatch):
    monkeypatch.setattr(rate_limit.time, "time", lambda: T_10_59_59)
    assert (await rate_limit.reserve_rate_limit_quota(7))[0] is True
    assert (await rate_limit.reserve_rate_limit_quota(7))[0] is True
    ok, key = await rate_limit.reserve_rate_limit_quota(7)
    assert ok is False and key is None
    assert list(coll.counts.values()) == [2]    # not 3


@pytest.mark.asyncio
async def test_release_without_a_key_is_a_no_op(coll):
    await rate_limit.release_rate_limit_quota(None)
    coll.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_limit_always_allows(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_HOUR", 0)
    assert await rate_limit.reserve_rate_limit_quota(7) == (True, None)


@pytest.mark.asyncio
async def test_fails_open_when_datastore_is_down(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_HOUR", 2)

    def boom():
        raise RuntimeError("mongo down")

    monkeypatch.setattr(rate_limit, "get_db", boom)
    assert await rate_limit.reserve_rate_limit_quota(7) == (True, None)


@pytest.mark.asyncio
async def test_push_releases_the_reserved_bucket_when_enqueue_fails(monkeypatch):
    from fastapi import HTTPException
    from app.routers import webhook as wh

    monkeypatch.setattr(wh, "reserve_rate_limit_quota", AsyncMock(return_value=(True, "7:42")))
    release = AsyncMock()
    monkeypatch.setattr(wh, "release_rate_limit_quota", release)
    monkeypatch.setattr(wh, "_safe_enqueue", AsyncMock(side_effect=HTTPException(503)))
    monkeypatch.setattr(wh, "enqueue_pipeline", MagicMock())

    payload = {"ref": "refs/heads/main", "after": "a" * 40,
               "repository": {"full_name": "acme/app", "default_branch": "main", "id": 1},
               "installation": {"id": 7}, "commits": [{"message": "feat"}]}
    with pytest.raises(HTTPException):
        await wh._handle_push(payload)
    release.assert_awaited_once_with("7:42")


@pytest.mark.asyncio
async def test_push_is_rate_limited_without_a_separate_check(monkeypatch):
    from app.routers import webhook as wh

    monkeypatch.setattr(wh, "reserve_rate_limit_quota", AsyncMock(return_value=(False, None)))
    payload = {"ref": "refs/heads/main", "after": "a" * 40,
               "repository": {"full_name": "acme/app", "default_branch": "main", "id": 1},
               "installation": {"id": 7}, "commits": [{"message": "feat"}]}
    assert (await wh._handle_push(payload))["status"] == "rate_limited"
