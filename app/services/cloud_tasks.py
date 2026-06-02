from google.cloud import tasks_v2
from google.protobuf import duration_pb2
from app.config import settings
import json, logging

logger = logging.getLogger(__name__)
client = tasks_v2.CloudTasksClient()

QUEUE_PATH = client.queue_path(
    settings.GOOGLE_CLOUD_PROJECT,
    settings.GCP_REGION,
    "synkron-pipeline-queue"
)


def _create_task(endpoint: str, payload: dict) -> str:
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{settings.SERVICE_URL}/internal/{endpoint}",
            "headers": {
                "Content-Type": "application/json",
                "X-Internal-Token": settings.INTERNAL_SECRET
            },
            "body": json.dumps(payload).encode()
        },
        "retry_config": {
            "max_attempts": 3,
            "min_backoff": duration_pb2.Duration(seconds=30),
            "max_backoff": duration_pb2.Duration(seconds=120),
        }
    }
    response = client.create_task(parent=QUEUE_PATH, task=task)
    return response.name


async def enqueue_pipeline(payload: dict):
    name = _create_task("run-pipeline", payload)
    logger.info(f"Pipeline task created: {name}")


async def enqueue_feedback(payload: dict):
    name = _create_task("process-feedback", payload)
    logger.info(f"Feedback task created: {name}")