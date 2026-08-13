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

def _task_exists(task_name: str) -> bool:
    """Check if a Cloud Task with the given name exists."""
    from google.cloud import tasks_v2
    from google.api_core.exceptions import NotFound
    if not task_name:
        return False
    client = _get_client()
    full_task_path = client.task_path(
        settings.GOOGLE_CLOUD_PROJECT, settings.GCP_REGION,
        "synkron-pipeline-queue", task_name)
    try:
        client.get_task(name=full_task_path)
        return True
    except NotFound:
        return False
    except Exception as e:
        logger.warning(f"Failed to check task existence for {task_name}: {e}")
        return False

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

        # Extract repo_id from GitHub payload
        repo_id = payload.get("repository", {}).get("id")
        if not repo_id:
            logger.error("Missing repository.id in GitHub payload")
            return

        asyncio.create_task(
            run_pipeline(
                before_sha=payload.get("before"),
                after_sha=payload.get("after"),
                repo_id=repo_id,
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

async def enqueue_feedback(payload: dict, delivery_id: str = ""):
    if settings.LOCAL_DEV:
        import asyncio
        from app.services.feedback import process_feedback
        logger.info("[LOCAL] Executing feedback process directly in background task")
        asyncio.create_task(process_feedback(payload))
        return
    # Use delivery_id as Cloud Task name for built-in deduplication (~1 hour window).
    # Task names must be alphanumeric + hyphens, so prefix the delivery ID (which is a UUID).
    # Dispatch synchronous Cloud Tasks API call to thread pool to avoid blocking event loop
    import asyncio
    task_name_template = f"gh-fb-{delivery_id}" if delivery_id else None
    task_name = await asyncio.to_thread(_create_task, 'process-feedback', payload, task_name_template)
    logger.info(f"Feedback task created: {task_name}")