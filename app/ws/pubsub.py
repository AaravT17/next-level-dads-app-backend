from app.config.redis import get_redis
from redis.asyncio.client import PubSub
import asyncio


pubsub_client: PubSub | None = None
pubsub_task: asyncio.Task | None = None


async def init_pubsub():
    global pubsub_client, pubsub_task
    redis_client = get_redis()
    try:
        pubsub_client = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub_task = asyncio.create_task(pubsub_client.run())
    except Exception as _:
        raise RuntimeError('Failed to initialize Pub/Sub')


def get_pubsub() -> PubSub:
    if pubsub_client is None:
        raise RuntimeError('Pub/Sub not initialized.')
    return pubsub_client


async def close_pubsub():
    global pubsub_client, pubsub_task
    if pubsub_client:
        try:
            await pubsub_client.unsubscribe()
        except Exception as _:
            # add proper logging here
            pass
        try:
            await pubsub_client.aclose()
        except Exception as _:
            # add proper logging here
            pass
        pubsub_client = None
    if pubsub_task:
        pubsub_task.cancel()
        try:
            await pubsub_task
        except asyncio.CancelledError:
            pass
        pubsub_task = None
