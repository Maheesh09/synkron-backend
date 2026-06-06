from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import settings
import logging
import dns.resolver
from pymongo.errors import OperationFailure


async def _ensure_index(coll, keys, **opts):
    try:
        await coll.create_index(keys, **opts)
    except OperationFailure as e:
        if e.code == 86:  # IndexKeySpecsConflict: same name, different options
            logger.warning(f"Index {keys} already exists with different options — skipping")
        else:
            raise

# Use Google's public DNS to resolve SRV records and avoid local router DNS timeouts
dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
dns.resolver.default_resolver.nameservers = ['8.8.8.8', '1.1.1.1']

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
        await _ensure_index(db.pipeline_runs, [("repo_id", 1), ("created_at", -1)])
        await _ensure_index(db.pipeline_runs, [("mr_id", 1)])
        await _ensure_index(db.correction_patterns, [("repo_id", 1), ("doc_type", 1), ("created_at", -1)])
        await _ensure_index(db.repositories, [("repo_id", 1)], unique=True)
        await _ensure_index(db.pipeline_run_details, [("run_id", 1), ("doc_path", 1)], unique=True)
        await _ensure_index(db.repositories, [("webhook_token_hash", 1)])
        
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        raise


async def disconnect_db():
    if client:
        client.close()


def get_db() -> AsyncIOMotorDatabase:
    return db