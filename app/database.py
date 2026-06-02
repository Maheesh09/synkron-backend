from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import settings
import logging

logger = logging.getLogger(__name__)

client: AsyncIOMotorClient = None
db: AsyncIOMotorDatabase = None


async def connect_db():
    global client, db
    try:
        client = AsyncIOMotorClient(settings.MONGODB_URI)
        db = client[settings.MONGODB_DB_NAME]
        await client.admin.command("ping")
        logger.info("MongoDB connected")

        # Create indexes
        await db.pipeline_runs.create_index([("repo_id", 1), ("created_at", -1)])
        await db.pipeline_runs.create_index([("mr_id", 1)])
        await db.correction_patterns.create_index(
            [("repo_id", 1), ("doc_type", 1), ("created_at", -1)]
        )
        await db.repositories.create_index([("repo_id", 1)], unique=True)
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        raise


async def disconnect_db():
    if client:
        client.close()


def get_db() -> AsyncIOMotorDatabase:
    return db