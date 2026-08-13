"""Per-installation rate limiting, backed by MongoDB so it holds across Cloud
Run instances. Fixed hourly window; fails open on datastore errors."""

import time
import logging
from datetime import datetime, timezone

from pymongo import ReturnDocument

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)


async def within_rate_limit(installation_id: int) -> bool:
    """
    True if this installation is within its hourly run budget, False if it has
    exceeded it. Counts every pipeline-triggering push, since each one costs at
    least one Gemini call. Fails open (returns True) if the datastore is
    unavailable, so a Mongo blip never blocks legitimate runs.
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
        logger.warning(f"Rate limit check failed for installation {installation_id}, allowing: {e}")
        return True