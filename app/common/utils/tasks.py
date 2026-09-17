import asyncio
import logging

from app.common.config.redis import publish

logger = logging.getLogger(__name__)

# The event loop holds only a *weak* reference to a task, so a fire-and-forget
# create_task() whose return value is discarded can be garbage-collected before
# it finishes. That surfaces as a WebSocket event that silently never arrives --
# rare, unreproducible, and invisible because safe_publish swallows errors.
# Keeping a strong reference until the task completes is the documented fix.
_background_tasks: set[asyncio.Task] = set()


def spawn(coro) -> None:
    """Run a coroutine in the background and keep it alive until it finishes."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def safe_publish(channel: str, event: dict) -> None:
    """Publish a Redis Pub/Sub event, logging and swallowing errors."""
    try:
        await publish(channel, event)
    except Exception:
        logger.exception('Failed to publish %s event to channel %s', event.get('type'), channel)
