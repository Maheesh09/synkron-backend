"""Per-installation rate limiting, backed by MongoDB so it holds across Cloud
Run instances. Fixed hourly window; fails open on datastore errors."""

import time
import logging
from datetime import datetime, timezone

from pymongo import ReturnDocument

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)


async def check_rate_limit(installation_id: int) -> bool:
    """
    True if this installation is within its hourly run budget, False if it has
    exceeded it. Does NOT increment the counter; use reserve_rate_limit_quota
    to actually reserve a slot. Fails open (returns True) if the datastore is
    unavailable, so a Mongo blip never blocks legitimate runs.
    """
    limit = settings.RATE_LIMIT_PER_HOUR
    if limit <= 0:
        return True  # disabled

    window = int(time.time()) // 3600           # current hour bucket
    key = f"{installation_id}:{window}"
    try:
        doc = await get_db().rate_limits.find_one({"_id": key})
        if doc is None:
            return True
        return doc["count"] < limit
    except Exception as e:
        logger.warning(f"Rate limit check failed for installation {installation_id}, allowing: {e}")
        return True

async def reserve_rate_limit_quota(installation_id: int) -> bool:
    """
    Reserve a quota slot for this installation. Returns True if quota was
    successfully reserved, False if the limit has been exceeded. Should be called
    after check_rate_limit and only when task creation will definitely proceed.
    """
    limit = settings.RATE_LIMIT_PER_HOUR
    if limit <= 0:
        return True  # disabled

    window = int(time.time()) // 3600           # current hour bucket
    key = f"{installation_id}:{window}"
    try:
        doc = await get_db().rate_limits.find_one_and_update(
            {"_id": key},
            {"$inc": {"count": 1},
             "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc["count"] <= limit
    except Exception as e:
        logger.warning(f"Rate limit reservation failed for installation {installation_id}, allowing: {e}")
        return True

async def release_rate_limit_quota(installation_id: int):
    """
    Release a previously reserved quota slot. Should be called if task creation
    fails after quota was reserved.
    """
    limit = settings.RATE_LIMIT_PER_HOUR
    if limit <= 0:
        return  # disabled

    window = int(time.time()) // 3600           # current hour bucket
    key = f"{installation_id}:{window}"
    try:
        await get_db().rate_limits.update_one(
            {"_id": key},
            {"$inc": {"count": -1}},
        )
        logger.info(f"Released rate limit quota for installation {installation_id}")
    except Exception as e:
        logger.warning(f"Failed to release rate limit quota for installation {installation_id}: {e}")

async def within_rate_limit(installation_id: int) -> bool:
    """
    DEPRECATED: Use check_rate_limit() and reserve_rate_limit_quota() separately.
    This function increments immediately and is kept for backward compatibility.
    """
    return await reserve_rate_limit_quota(installation_id)