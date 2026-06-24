"""MongoDB connection lifecycle using Motor (async)."""
import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

logger = logging.getLogger(__name__)


class _MongoState:
    client: AsyncIOMotorClient | None = None
    db: AsyncIOMotorDatabase | None = None


mongo = _MongoState()


async def connect_to_mongo() -> None:
    """Open the Motor client. Called on app startup."""
    logger.info("Connecting to MongoDB at %s", settings.MONGODB_URI)
    # tz_aware=True → datetimes read back from Mongo are timezone-aware UTC, so
    # timestamp math and API serialization aren't skewed by the server's local tz.
    mongo.client = AsyncIOMotorClient(settings.MONGODB_URI, tz_aware=True)
    mongo.db = mongo.client[settings.MONGODB_DB_NAME]
    # Fail fast if unreachable.
    await mongo.client.admin.command("ping")
    logger.info("MongoDB connection established (db=%s)", settings.MONGODB_DB_NAME)


async def close_mongo_connection() -> None:
    """Close the Motor client. Called on app shutdown."""
    if mongo.client is not None:
        mongo.client.close()
        logger.info("MongoDB connection closed")


def get_database() -> AsyncIOMotorDatabase:
    """Return the active database handle (used by repositories/deps)."""
    if mongo.db is None:
        raise RuntimeError("Database not initialized. Did the app start up correctly?")
    return mongo.db
