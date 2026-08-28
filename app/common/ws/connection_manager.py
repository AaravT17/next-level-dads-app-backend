from fastapi import WebSocket
from app.common.config.pubsub import get_pubsub
import json
import asyncio


_user_connections: dict[str, dict[str, WebSocket]] = {}  # tracks active WebSocket connections for each user
_chat_subscribers: dict[str, set[str]] = {}  # maps chat -> set of users subscribed to that chat
_user_chats: dict[str, set[str]] = {}  # maps user -> chats that the user is subscribed to
_users_initialized: set[str] = set()  # set of users whose initial chat subscription setup is complete
lock = asyncio.Lock()


async def register_connection(user_id: str, connection_id: str, ws: WebSocket):
    """
    Register a new WebSocket connection for a user. If this is the first connection for the user, subscribe to their
    pubsub channel 'user:{user_id}'.
    """
    async with lock:
        if user_id in _user_connections:
            _user_connections[user_id][connection_id] = ws
        else:
            _user_connections[user_id] = {connection_id: ws}
            await get_pubsub().subscribe(**{f'user:{user_id}': _process_user_event})


async def initialize_user_chats(user_id: str, chat_ids: set[str]):
    """
    Initialize the user's chat subscriptions and subscribe to the corresponding pubsub channels: 'chat:{chat_id}' for
    each chat_id in chat_ids.
    """
    async with lock:
        if len(chat_ids) > 0:
            if user_id in _user_chats:
                _user_chats[user_id].update(chat_ids)
            else:
                _user_chats[user_id] = set(chat_ids)  # assign a new set rather than the original set

            for chat_id in chat_ids:
                if chat_id in _chat_subscribers:
                    _chat_subscribers[chat_id].add(user_id)
                else:
                    _chat_subscribers[chat_id] = {user_id}

            await get_pubsub().subscribe(**{f'chat:{chat_id}': _process_chat_event for chat_id in chat_ids})

        _users_initialized.add(user_id)


def is_user_initialized(user_id: str) -> bool:
    """Check if the user's initial chat subscription setup is complete."""
    return user_id in _users_initialized


async def unregister_connection(user_id: str, connection_id: str):
    """
    Unregister a WebSocket connection for a user. If this was the last connection for the user, unsubscribe from their
    pubsub channel 'user:{user_id}' and all chat channels for which they were the last remaining subscriber.
    """
    async with lock:
        if user_id not in _user_connections:
            # this is the case if ws.accept() failed and the connection was never registered
            return

        _user_connections[user_id].pop(connection_id, None)
        if _user_connections[user_id] == {}:
            # this is the last connection for the user, clean up their subscriptions
            _user_connections.pop(user_id, None)
            _users_initialized.discard(user_id)

            # maintain a list of channels to unsubscribe from, unsubscribe from all of them in one call to
            # pubsub.unsubscribe() at the end to avoid multiple network round trips
            unsub_channels = [f'user:{user_id}']

            if user_id in _user_chats:
                for chat_id in _user_chats[user_id]:
                    _chat_subscribers[chat_id].discard(user_id)
                    if not _chat_subscribers[chat_id]:
                        # no more subscribers for this chat, unsubscribe from the pubsub channel
                        _chat_subscribers.pop(chat_id, None)
                        unsub_channels.append(f'chat:{chat_id}')

                _user_chats.pop(user_id, None)

            try:
                await get_pubsub().unsubscribe(*unsub_channels)
            except Exception as e:
                print(f'Failed to unsubscribe from channels: {", ".join(unsub_channels)}: {e}')


# --- Event handlers for pubsub messages ---
# msg is a dict with keys: type, channel, data
# subscribe/unsubscribe confirmation messages are suppressed via ignore_subscribe_messages=True on the pubsub client
# the actual event we publish is in msg['data'], which is a JSON string that we need to parse
async def _process_user_event(msg: dict):
    try:
        event = json.loads(msg['data'])
    except json.JSONDecodeError:
        return

    user_id = msg['channel'].split(':')[1]  # channel='user:{user_id}'

    event_type = event['type']
    if event_type == 'chats:added':
        chat_id = event['payload']['chat_id']
        await _process_chats_added(user_id, chat_id)
    elif event_type == 'chats:removed':
        chat_id = event['payload']['chat_id']
        await _process_chats_removed(user_id, chat_id)

    # broadcast the event to all active connections ws for the user
    user_ws_dict = _user_connections.get(user_id, {})
    if user_ws_dict:
        # capture a snapshot of active ws connections for the user, prevents runtime errors in case it changes mid-loop
        wss = list(user_ws_dict.values())
        await asyncio.gather(*[_safe_send(ws, event) for ws in wss])


async def _process_chats_added(user_id: str, chat_id: str):
    # If we fail to subscribe to the pubsub channel, we do not want to add the user to the chat's subscriber list or
    # the chat to the user's chat list since we won't be able to send them events for that chat.
    async with lock:
        if chat_id in _chat_subscribers:
            _chat_subscribers[chat_id].add(user_id)
        else:
            try:
                await get_pubsub().subscribe(**{f'chat:{chat_id}': _process_chat_event})
                _chat_subscribers[chat_id] = {user_id}
            except Exception as e:
                print(f"Failed to subscribe to channel 'chat:{chat_id}' for user {user_id}: {e}")
                return

        if user_id in _user_chats:
            _user_chats[user_id].add(chat_id)
        else:
            _user_chats[user_id] = {chat_id}


async def _process_chats_removed(user_id: str, chat_id: str):
    # Even if we fail to unsubscribe from the pubsub channel, we still want to remove the user from the chat's
    # subscriber list and the chat from the user's chat list since the user is no longer subscribed to that chat
    # and so we no longer want to send them events for that chat.
    async with lock:
        if chat_id in _chat_subscribers:
            _chat_subscribers[chat_id].discard(user_id)
            if not _chat_subscribers[chat_id]:
                # no more subscribers for this chat, unsubscribe from the pubsub channel
                _chat_subscribers.pop(chat_id, None)
                try:
                    await get_pubsub().unsubscribe(f'chat:{chat_id}')
                except Exception as e:
                    print(f"Failed to unsubscribe from channel 'chat:{chat_id}': {e}")

        if user_id in _user_chats:
            _user_chats[user_id].discard(chat_id)
            if not _user_chats[user_id]:
                _user_chats.pop(user_id, None)


async def _process_chat_event(msg: dict):
    try:
        event = json.loads(msg['data'])
    except json.JSONDecodeError:
        return

    # broadcast the event to all active ws connections for all users subscribed to the chat
    chat_id = msg['channel'].split(':')[1]  # channel='chat:{chat_id}'
    wss = []
    for user_id in _chat_subscribers.get(chat_id, set()):
        user_ws_dict = _user_connections.get(user_id, {})
        wss.extend(user_ws_dict.values())

    await asyncio.gather(*[_safe_send(ws, event) for ws in wss])


async def send_event(ws: WebSocket, event: dict):
    """Send event data over a WebSocket connection."""
    await ws.send_json(event)


async def _safe_send(ws: WebSocket, event: dict):
    """Send event data over a WebSocket connection. Catches any exceptions that occur."""
    try:
        await send_event(ws, event)
    except Exception as e:
        print(f'Failed to send event over WebSocket: {e}')
