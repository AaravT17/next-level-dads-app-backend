from fastapi import APIRouter, status, Query, WebSocket, WebSocketDisconnect
import app.modules.auth.service as auth_service
from app.common.dependencies.auth import check_consent
from app.common.ws.connection_manager import (
    register_connection,
    unregister_connection,
    initialize_user_chats,
    send_event,
    is_user_initialized,
)
from app.common.config.redis import publish
import app.modules.chats.service as chats_service
import json


router = APIRouter(
    prefix='/api/ws',
    tags=['ws'],
)


@router.websocket('/')
async def chat_websocket(ws: WebSocket, token: str = Query(..., min_length=1), connection_id: str = Query(...)):
    # TODO: Frontend should rotate connection IDs on reconnects
    user_id = await auth_service.verify_token(token)
    if not user_id:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with ws.app.state.pool.acquire() as conn:
        consented = await check_consent(conn, user_id)
    if not consented:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        await ws.accept()
        await register_connection(user_id, connection_id, ws)
        if not is_user_initialized(user_id):
            async with ws.app.state.pool.acquire() as conn:
                chat_ids = await chats_service.get_user_chat_ids(conn, user_id)
            await initialize_user_chats(user_id, chat_ids)
        # send a "ready" event to the client to indicate that the WebSocket connection setup is complete
        await send_event(ws, {'type': 'ws:ready'})
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except (json.JSONDecodeError, TypeError):
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
                            f'user:{user_id}',
                            {
                                'type': 'chats:read',
                                'payload': {
                                    'chat_id': chat_id,
                                    'last_read_at': last_read_at.isoformat(),
                                },
                            },
                        )
                except Exception:
                    pass

    except WebSocketDisconnect:
        # the connection has already been closed, need not call ws.close() here
        pass
    except Exception as _:
        # some error occurred, close the connection
        try:
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception as _:
            # ws.accept() may fail, in which case ws.close() above will also fail, but we can ignore that since
            # the connection is already closed
            pass
    finally:
        await unregister_connection(user_id, connection_id)
