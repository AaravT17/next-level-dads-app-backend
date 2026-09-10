import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from fastapi_limiter.depends import WebSocketRateLimiter

import app.modules.auth.service as auth_service
import app.modules.chats.service as chats_service
from app.common.config.constants import IS_PRODUCTION
from app.common.config.redis import publish
from app.common.dependencies.auth import check_consent
from app.common.ws.connection_manager import connect, disconnect
from app.modules.ws.auth import BEARER_SUBPROTOCOL, extract_bearer_token, token_expiry

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix='/api/ws',
    tags=['ws'],
)

# The socket carries no per-message auth, so an unbounded loop is an unbounded
# invitation: every `chats:read` takes a connection from a pool of ten that the
# whole HTTP surface shares. Sixty a minute is far above what marking threads
# read requires and far below what would starve the pool.
_MESSAGE_LIMIT_TIMES = 60
_MESSAGE_LIMIT_SECONDS = 60


async def _over_budget(ws: WebSocket, pexpire: int) -> bool:
    """Signal rejection by return value rather than by raising.

    The library's default callback raises `HTTPException`, which means nothing
    on an established socket -- there is no response left to attach a 429 to.
    Returning a flag lets the loop drop the message and keep the connection,
    which is the behaviour that actually makes sense here.
    """
    return True


def _message_limiter(user_id: str) -> WebSocketRateLimiter | None:
    """Per-user limiter for the socket's inbound messages.

    The identifier is the authenticated user, not an IP. The library default
    would read the *leftmost* `X-Forwarded-For` entry -- the client-supplied one
    -- which is the bypass the HTTP limiters were fixed for; keying on the
    identity we already proved at connect avoids the question entirely.
    """
    # FastAPILimiter is only initialised in production (see main.py), and the
    # limiter raises without it.
    if not IS_PRODUCTION:
        return None

    async def identifier(_ws: WebSocket) -> str:
        return user_id

    return WebSocketRateLimiter(
        times=_MESSAGE_LIMIT_TIMES,
        seconds=_MESSAGE_LIMIT_SECONDS,
        identifier=identifier,
        callback=_over_budget,
    )


async def _close_at(ws: WebSocket, expires_at: datetime) -> None:
    """Close the socket once the token that opened it has expired.

    The connect-time check is the only authorisation this connection ever gets,
    so without this a socket outlives its token for as long as the process runs.
    Closing with 1008 is what the client already expects for an auth failure: it
    refreshes and reconnects, so an active user sees nothing.
    """
    delay = (expires_at - datetime.now(UTC)).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
    except Exception:
        logger.debug('Socket already closed when its token expired', exc_info=True)


@router.websocket('/')
async def chat_websocket(ws: WebSocket):
    # The token arrives as a subprotocol rather than a query parameter, so it
    # stays out of the request line and therefore out of every access log
    # between the browser and here.
    token = extract_bearer_token(ws.headers.get('sec-websocket-protocol'))
    if not token:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = await auth_service.verify_token(token)
    if not user_id:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with ws.app.state.pool.acquire() as conn:
        consented = await check_consent(conn, user_id)
    if not consented:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Generated here, never taken from the client. A client-chosen id is a key
    # into a process-wide map: two sockets sharing one would have the first's
    # teardown evict the second, leaving a socket that is open but unreachable.
    connection_id = str(uuid4())
    expires_at = token_expiry(token)
    expiry_task: asyncio.Task | None = None
    limiter = _message_limiter(user_id)

    try:
        await connect(user_id, connection_id, ws, subprotocol=BEARER_SUBPROTOCOL)
        if expires_at is not None:
            expiry_task = asyncio.create_task(_close_at(ws, expires_at))

        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue

            # Drop the message, keep the socket: a client over budget is
            # usually a loop in the client, not someone to disconnect.
            if limiter is not None and await limiter(ws, context_key='messages'):
                logger.warning('Rate-limited a WebSocket message from user %s', user_id)
                continue

            if msg.get('type') == 'chats:read':
                chat_id = msg.get('chat_id')
                if not chat_id:
                    continue
                try:
                    async with ws.app.state.pool.acquire() as conn:
                        last_read_at = await chats_service.mark_chat_read(conn, user_id, chat_id)
                    if last_read_at:
                        await publish(
                            user_id,
                            {
                                'user_id': user_id,
                                'event_data': {
                                    'type': 'chats:read',
                                    'payload': {
                                        'chat_id': chat_id,
                                        'last_read_at': last_read_at.isoformat(),
                                    },
                                },
                            },
                        )
                except Exception:
                    logger.exception('Failed to mark chat %s read for user %s', chat_id, user_id)

    except WebSocketDisconnect:
        # the connection has already been closed, need not call ws.close() here
        pass
    except Exception:
        logger.exception('WebSocket handler failed for user %s', user_id)
        # some error occurred, close the connection
        try:
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            # ws.accept() may fail, in which case ws.close() above will also fail, but we can ignore that since
            # the connection is already closed
            pass
    finally:
        if expiry_task is not None:
            expiry_task.cancel()
        # Passing the socket makes this a no-op if the map has already moved on.
        await disconnect(user_id, connection_id, ws)
