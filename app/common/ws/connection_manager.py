from fastapi import WebSocket
from app.common.config.pubsub import get_pubsub
import json
import asyncio
import logging

logger = logging.getLogger(__name__)


# Published on a user's channel to tear down their live sockets. Closing with
# 1008 puts the client on its existing auth-failure path: it refreshes and
# reconnects, which succeeds if the session is still good and logs the user out
# if it is not.
SESSION_REVOKED_EVENT = 'session:revoked'
WS_POLICY_VIOLATION = 1008

_user_connections: dict[str, dict[str, WebSocket]] = {}  # tracks active WebSocket connections for each user
_chat_subscribers: dict[str, set[str]] = {}  # maps chat -> set of users subscribed to that chat
_user_chats: dict[str, set[str]] = {}  # maps user -> chats that the user is subscribed to
_users_initialized: set[str] = set()  # set of users whose initial chat subscription setup is complete
lock = asyncio.Lock()


async def register_connection(user_id: str, connection_id: str, ws: WebSocket, subprotocol: str | None = None):
    """
    Accept and register a new WebSocket connection for a user. If this is the first connection for the user, subscribe
    to their pubsub channel 'user:{user_id}'.

    `subprotocol` echoes back the one the client offered. RFC 6455 requires the server to name exactly one of the
    offered protocols, or the browser fails the connection. The accept happens here rather than in the router so that
    a failed handshake leaves nothing registered.
    """
    await ws.accept(subprotocol=subprotocol)
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


async def unregister_connection(user_id: str, connection_id: str, ws: WebSocket | None = None):
    """
    Unregister a WebSocket connection for a user. If this was the last connection for the user, unsubscribe from their
    pubsub channel 'user:{user_id}' and all chat channels for which they were the last remaining subscriber.

    The `ws` identity check is what makes a late disconnect harmless. Connection ids are generated server-side so a
    collision should be impossible, but a teardown arriving after the entry was replaced would otherwise evict a live
    socket -- and the client would never know, because its socket is still open and no `onclose` fires. It would
    simply stop receiving events.
    """
    async with lock:
        if user_id not in _user_connections:
            # this is the case if ws.accept() failed and the connection was never registered
            return

        if ws is not None and _user_connections[user_id].get(connection_id) is not ws:
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
            except Exception:
                logger.warning(
                    'Failed to unsubscribe from channels: %s', ', '.join(unsub_channels), exc_info=True
                )


async def close_user_connections(user_id: str, code: int) -> None:
    """Close every socket a user has open.

    A socket is authorised once, at connect. Without this, revoking a session leaves its already-open sockets
    streaming that user's messages until the process restarts -- the server has no other way to reach an established
    connection.
    """
    async with lock:
        sockets = list(_user_connections.get(user_id, {}).values())

    for ws in sockets:
        try:
            await ws.close(code=code)
        except Exception:
            # Already gone; the socket's own handler runs unregister_connection().
            logger.debug('Failed to close a WebSocket during revocation', exc_info=True)


# --- Event handlers for pubsub messages ---
# msg is a dict with keys: type, channel, data
# subscribe/unsubscribe confirmation messages are suppressed via ignore_subscribe_messages=True on the pubsub client
# the actual event we publish is in msg['data'], which is a JSON string that we need to parse
#
# Every failure path here returns instead of raising. These run inside the single pub/sub reader task, and an
# exception escaping one ends that task -- which stops WebSocket delivery for *every* user in the process, with no
# health signal and no restart. One malformed payload must not cost that.
def _parse_event(msg: dict) -> dict | None:
    """Parse a pub/sub message into an event dict, or None if it is unusable."""
    try:
        event = json.loads(msg['data'])
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning('Discarded unparseable pub/sub message')
        return None

    if not isinstance(event, dict):
        logger.warning('Discarded pub/sub message that was not an object')
        return None

    return event


def _channel_id(msg: dict) -> str | None:
    """Pull the id out of a 'user:{id}' or 'chat:{id}' channel name."""
    channel = msg.get('channel')
    if isinstance(channel, bytes):
        channel = channel.decode()
    if not isinstance(channel, str) or ':' not in channel:
        logger.warning('Discarded pub/sub message with an unreadable channel')
        return None

    return channel.split(':', 1)[1]


async def _process_user_event(msg: dict):
    event = _parse_event(msg)
    if event is None:
        return

    user_id = _channel_id(msg)  # channel='user:{user_id}'
    if not user_id:
        return

    event_type = event.get('type')
    if event_type == SESSION_REVOKED_EVENT:
        # A control event, not something to deliver. Any process holding this
        # user's sockets drops them; the one that published it may hold none.
        await close_user_connections(user_id, WS_POLICY_VIOLATION)
        return

    if event_type == 'chats:added':
        chat_id = event.get('payload', {}).get('chat_id')
        if chat_id:
            await _process_chats_added(user_id, chat_id)
    elif event_type == 'chats:removed':
        chat_id = event.get('payload', {}).get('chat_id')
        if chat_id:
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
            except Exception:
                logger.warning(
                    "Failed to subscribe to channel 'chat:%s' for user %s", chat_id, user_id, exc_info=True
                )
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
                except Exception:
                    logger.warning("Failed to unsubscribe from channel 'chat:%s'", chat_id, exc_info=True)

        if user_id in _user_chats:
            _user_chats[user_id].discard(chat_id)
            if not _user_chats[user_id]:
                _user_chats.pop(user_id, None)


async def _process_chat_event(msg: dict):
    event = _parse_event(msg)
    if event is None:
        return

    # broadcast the event to all active ws connections for all users subscribed to the chat
    chat_id = _channel_id(msg)  # channel='chat:{chat_id}'
    if not chat_id:
        return

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
    except Exception:
        # A dead or closing socket is routine; the disconnect handler cleans it
        # up. Log at debug so it does not drown the real errors.
        logger.debug('Dropped event for a closed WebSocket', exc_info=True)
