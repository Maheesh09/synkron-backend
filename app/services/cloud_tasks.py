from app.config import settings
import json, logging, os
import httpx

logger = logging.getLogger(__name__)

_client = None
def _get_client():
    global _client
    if _client is None:
        from google.cloud import tasks_v2
        _client = tasks_v2.CloudTasksClient()
    return _client

async def _dispatch_local(endpoint: str, payload: dict):
    """Local: POST straight to the internal endpoint, skipping Cloud Tasks."""
    url = f"{settings.SERVICE_URL}/internal/{endpoint}"
    async with httpx.AsyncClient(timeout=180.0) as c:
        r = await c.post(url, json=payload,
                         headers={"X-Internal-Token": settings.INTERNAL_SECRET})
        logger.info(f"[LOCAL] {endpoint} -> {r.status_code} {r.text[:200]}")

def _create_task(endpoint: str, payload: dict, task_name: str = None) -> str:
    from google.cloud import tasks_v2
    from google.protobuf import duration_pb2
    client = _get_client()
    queue_path = client.queue_path(
        settings.GOOGLE_CLOUD_PROJECT, settings.GCP_REGION, "synkron-pipeline-queue")
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{settings.SERVICE_URL}/internal/{endpoint}",
            "headers": {"Content-Type": "application/json",
                        "X-Internal-Token": settings.INTERNAL_SECRET},
            "body": json.dumps(payload).encode(),
        },
        # Give the task time to run the full agent pipeline (default is 10 min).
        "dispatch_deadline": duration_pb2.Duration(seconds=600),
    }
    # Optional task name for deduplication. Cloud Tasks deduplicates by name
    # for ~1 hour after creation/completion, providing additional protection
    # against webhook redeliveries that slip through our DB check.
    if task_name:
        task["name"] = client.task_path(
            settings.GOOGLE_CLOUD_PROJECT, settings.GCP_REGION,
            "synkron-pipeline-queue", task_name)
    return client.create_task(parent=queue_path, task=task).name

async def enqueue_pipeline(payload: dict, delivery_id: str = ""):
    if settings.LOCAL_DEV:
        import asyncio
        from app.agents.orchestrator import run_pipeline
        logger.info("[LOCAL] Executing pipeline directly in background task")
        asyncio.create_task(
            run_pipeline(
                before_sha=payload.get("before"),
                after_sha=payload.get("after"),
                repo_id=payload.get("project", {}).get("id"),
                payload=payload
            )
        )
        return
    # Use delivery_id as Cloud Task name for built-in deduplication (~1 hour window).
    # Task names must be alphanumeric + hyphens, so prefix the delivery ID (which is a UUID).
    # Dispatch synchronous Cloud Tasks API call to thread pool to avoid blocking event loop
    import asyncio
    task_name_template = f"gh-{delivery_id}" if delivery_id else None
    task_name_created = await asyncio.to_thread(_create_task, 'run-pipeline', payload, task_name_template)
    logger.info(f"Pipeline task created: {task_name_created}")

async def enqueue_feedback(payload: dict):
    if settings.LOCAL_DEV:
        import asyncio
        from app.services.feedback import process_feedback
        logger.info("[LOCAL] Executing feedback process directly in background task")
        asyncio.create_task(process_feedback(payload))
        return
    # Dispatch synchronous Cloud Tasks API call to thread pool to avoid blocking event loop
    import asyncio
    task_name = await asyncio.to_thread(_create_task, 'process-feedback', payload)
    logger.info(f"Feedback task created: {task_name}")