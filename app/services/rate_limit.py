"""Per-installation rate limiting, backed by MongoDB so it holds across Cloud
Run instances. Fixed hourly window; fails open on datastore errors."""

import time
import logging
from datetime import datetime, timezone

from pymongo import ReturnDocument

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)


def _bucket_key(installation_id: int) -> str:
    return f"{installation_id}:{int(time.time()) // 3600}"   # current hour bucket


async def reserve_rate_limit_quota(installation_id: int) -> tuple[bool, str | None]:
    """
    Atomically reserve one run for this installation in the current hour.

    Returns (ok, key). Pass `key` to release_rate_limit_quota if the run is
    not enqueued after all, so the release hits the same hour bucket even if
    the clock has rolled over in between. key is None when there is nothing to
    release (limit disabled, limit exceeded, or datastore unavailable).
    Fails open, so a Mongo blip never blocks legitimate runs.
    """
    limit = settings.RATE_LIMIT_PER_HOUR
    if limit <= 0:
        return True, None  # disabled

    key = _bucket_key(installation_id)
    try:
        coll = get_db().rate_limits
        doc = await coll.find_one_and_update(
            {"_id": key},
            {"$inc": {"count": 1},
             "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if doc["count"] <= limit:
            return True, key
        # Over the limit: undo our increment so the counter stays accurate.
        await coll.update_one({"_id": key}, {"$inc": {"count": -1}})
        return False, None
    except Exception as e:
        logger.warning(f"Rate limit reservation failed for installation {installation_id}, allowing: {e}")
        return True, None


async def release_rate_limit_quota(key: str | None) -> None:
    """Give back a slot taken by reserve_rate_limit_quota (e.g. enqueue failed)."""
    if not key:
        return
    try:
        await get_db().rate_limits.update_one({"_id": key}, {"$inc": {"count": -1}})
        logger.info(f"Released rate limit quota for bucket {key}")
    except Exception as e:
        logger.warning(f"Failed to release rate limit quota for bucket {key}: {e}")
