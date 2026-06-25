from fastapi import WebSocket
from app.ws.pubsub import get_pubsub
import json
import asyncio


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
            # no active connections left for the user, remove entry from active_connections and unsubscribe from channel
            active_connections.pop(user_id, None)
            await get_pubsub().unsubscribe(f'messages:{user_id}')


async def handle_event(msg: dict):
    # msg is a dict with keys: type, channel, data
    # subscribe/unsubscribe confirmation messages are suppressed via ignore_subscribe_messages=True on the pubsub client
    try:
        data = json.loads(msg['data'])  # data contains the actual payload we published
    except json.JSONDecodeError:
        # failed to decode event
        return

    # broadcast the event to all active connections for the user
    user_ws_dict = active_connections.get(data['user_id'])
    if user_ws_dict:
        # capture a snapshot of active connections for the user, prevents runtime errors
        # in case it changes mid-loop while we're broadcasting
        user_ws = list(user_ws_dict.values())
        for ws in user_ws:
            try:
                await ws.send_json(data['event_data'])
            except Exception as _:
                # an error may occur if an event arrives between WebSocket closure and disconnect being called
                pass
