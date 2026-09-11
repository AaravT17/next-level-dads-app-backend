from app.common.config.redis import get_redis
from redis.asyncio.client import PubSub
import asyncio
import logging

logger = logging.getLogger(__name__)


pubsub_client: PubSub | None = None
pubsub_task: asyncio.Task | None = None


async def init_pubsub():
    global pubsub_client, pubsub_task
    redis_client = get_redis()
    try:
        pubsub_client = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub_task = asyncio.create_task(pubsub_client.run())
        pubsub_task.add_done_callback(_log_reader_exit)
    except Exception:
        raise RuntimeError('Failed to initialize Pub/Sub')


def _log_reader_exit(task: asyncio.Task) -> None:
    """Say so, loudly, if the pub/sub reader stops.

    There is exactly one reader task for the process. If it ends, every
    WebSocket event silently stops being delivered and nothing else notices --
    the sockets stay open, so clients look connected and simply receive
    nothing. Cancellation during shutdown is expected; anything else is not.

    This reports the failure, it does not recover from it. Re-running `run()`
    would not restore the per-user channel subscriptions, and a restart that
    silently drops them would be harder to diagnose than a clear log line.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.critical('Pub/Sub reader task died; WebSocket delivery has stopped', exc_info=exc)
    else:
        logger.critical('Pub/Sub reader task exited; WebSocket delivery has stopped')


def get_pubsub() -> PubSub:
    if pubsub_client is None:
        raise RuntimeError('Pub/Sub not initialized.')
    return pubsub_client


async def close_pubsub():
    global pubsub_client, pubsub_task
    if pubsub_client:
        try:
            await pubsub_client.unsubscribe()
        except Exception:
            pass
        try:
            await pubsub_client.aclose()
        except Exception:
            pass
        pubsub_client = None
    if pubsub_task:
        pubsub_task.cancel()
        try:
            await pubsub_task
        except asyncio.CancelledError:
            pass
        pubsub_task = None
