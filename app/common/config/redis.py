import redis.asyncio as redis
import os
import json

redis_client: redis.Redis | None = None

REDIS_URL = os.getenv('REDIS_URL', None)


def init_redis():
    global redis_client
    if not REDIS_URL:
        raise ValueError('REDIS_URL must be set in environment variables.')
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)


def get_redis() -> redis.Redis:
    if redis_client is None:
        raise RuntimeError('Redis client not initialized.')
    return redis_client


async def publish(user_id: str, msg: dict):
    # publishing is handled by the redis client, subscribing and listening is handled by the pubsub client
    await redis_client.publish(channel=f'messages:{user_id}', message=json.dumps(msg))


async def close_redis():
    if redis_client:
        await redis_client.aclose()
