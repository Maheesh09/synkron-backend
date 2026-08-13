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
            logging.warning(f"Index {keys} already exists with different options - skipping")
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
    # Build the client and bind the db first. serverSelectionTimeoutMS caps how
    # long any call waits for the server, so a down Atlas fails in seconds rather
    # than the 30s default, which would blow Cloud Run's startup probe.
    try:
        client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[settings.MONGODB_DB_NAME]
    except Exception as e:
        logging.exception(f"Failed to build MongoDB client, booting without a database: {e}")
        return

    # Verify reachability. If Mongo is down we still boot — db stays bound, so it
    # reconnects lazily on the first query once Atlas is reachable again.
    try:
        await client.admin.command("ping")
        logging.info("MongoDB connected")
    except Exception as e:
        logging.exception(f"MongoDB unreachable at startup, booting anyway (will retry on use): {e}")
        return

    # Connected — ensure indexes, best-effort so an index hiccup can't crash boot.
    try:
        await _ensure_index(db.pipeline_runs, [("repo_id", 1), ("created_at", -1)])
        await _ensure_index(db.pipeline_runs, [("mr_id", 1)])
        await _ensure_index(db.correction_patterns, [("repo_id", 1), ("doc_type", 1), ("created_at", -1)])
        await _ensure_index(db.repositories, [("repo_id", 1)], unique=True)
        await _ensure_index(db.pipeline_run_details, [("run_id", 1), ("doc_path", 1)], unique=True)
        await _ensure_index(db.repositories, [("webhook_token_hash", 1)])
        await _ensure_index(db.repositories, [("owner_uid", 1)])
        await _ensure_index(db.webhook_deliveries, [("delivery_id", 1)], unique=True)
        await _ensure_index(db.rate_limits, [("created_at", 1)], expireAfterSeconds=7200)
        
    except Exception as e:
        logging.exception(f"Index creation failed (non-fatal): {e}")


async def disconnect_db():
    if client:
        client.close()


def get_db() -> AsyncIOMotorDatabase:
    return db