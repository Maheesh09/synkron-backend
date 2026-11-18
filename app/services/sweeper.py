"""Close out pipeline runs whose container died mid-run.

If Cloud Run kills an instance (timeout, out of memory, redeploy) the
orchestrator's except block never runs, so the run would stay 'running'
forever. Cloud Scheduler calls POST /internal/sweep every 15 minutes; any run
whose latest attempt started more than 15 minutes ago is marked failed.
Cloud Tasks' dispatch deadline is 10 minutes, so no live attempt is that old.
"""

from datetime import datetime, timedelta
import logging

from app.database import get_db

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=15)


async def sweep_abandoned_runs(now: datetime | None = None) -> int:
    now = now or datetime.utcnow()   # stored timestamps are naive UTC
    cutoff = now - STALE_AFTER
    result = await get_db().pipeline_runs.update_many(
        {
            "status": "running",
            "$or": [
                {"last_attempt_at": {"$lt": cutoff}},
                # Runs created before last_attempt_at existed.
                {"last_attempt_at": {"$exists": False}, "created_at": {"$lt": cutoff}},
            ],
        },
        {"$set": {
            "status": "failed",
            "error_type": "Abandoned",
            "error_message": f"No progress for over {int(STALE_AFTER.total_seconds() // 60)} "
                             "minutes; the worker was likely stopped mid-run.",
        }},
    )
    if result.modified_count:
        logger.warning(f"Sweeper marked {result.modified_count} abandoned run(s) as failed")
    return result.modified_count
