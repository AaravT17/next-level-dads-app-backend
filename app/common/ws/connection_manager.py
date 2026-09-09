from fastapi import WebSocket
from app.common.config.pubsub import get_pubsub
import json
import asyncio
import logging

logger = logging.getLogger(__name__)


active_connections: dict[str, dict[str, WebSocket]] = {}
lock = asyncio.Lock()


async def connect(user_id: str, connection_id: str, ws: WebSocket):
    await ws.accept()
    async with lock:
        if user_id in active_connections:
            active_connections[user_id][connection_id] = ws
        else:
            active_connections[user_id] = {connection_id: ws}
            await get_pubsub().subscribe(**{f'messages:{user_id}': handle_event})


async def disconnect(user_id: str, connection_id: str):
    async with lock:
        if user_id not in active_connections:
            return

        active_connections[user_id].pop(connection_id, None)
        if active_connections[user_id] == {}:
            # no active connections left for the user, remove entry from active_connections + unsubscribe from channel
            active_connections.pop(user_id, None)
            await get_pubsub().unsubscribe(f'messages:{user_id}')


async def handle_event(msg: dict):
    """Fan one published event out to the recipient's live sockets.

    Every failure here returns instead of raising. This runs inside the single
    pub/sub reader task, and an exception escaping it ends that task -- which
    stops WebSocket delivery for *every* user in the process, with no health
    signal and no restart. One malformed payload must not cost that.
    """
    # msg is a dict with keys: type, channel, data
    # subscribe/unsubscribe confirmation messages are suppressed via ignore_subscribe_messages=True on the pubsub client
    try:
        data = json.loads(msg['data'])  # data contains the actual payload we published
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning('Discarded unparseable pub/sub message')
        return

    if not isinstance(data, dict):
        logger.warning('Discarded pub/sub message that was not an object')
        return

    user_id = data.get('user_id')
    event_data = data.get('event_data')
    if not user_id or event_data is None:
        logger.warning('Discarded pub/sub message missing user_id or event_data')
        return

    # broadcast the event to all active connections for the user
    user_ws_dict = active_connections.get(user_id)
    if user_ws_dict:
        # capture a snapshot of active connections for the user, prevents runtime errors in case it changes mid-loop
        user_ws = list(user_ws_dict.values())
        await asyncio.gather(*[_send_event(ws, event_data) for ws in user_ws])


async def _send_event(ws: WebSocket, event_data: dict):
    """Send event data over a WebSocket connection. Catches any exceptions that occur."""
    try:
        await ws.send_json(event_data)
    except Exception:
        # A dead or closing socket is routine; the disconnect handler cleans it
        # up. Log at debug so it does not drown the real errors.
        logger.debug('Dropped event for a closed WebSocket', exc_info=True)
