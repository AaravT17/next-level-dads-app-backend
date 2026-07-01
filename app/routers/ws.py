from fastapi import APIRouter, status, Query, WebSocket, WebSocketDisconnect
from app.utils.auth import verify_token, check_consent
from app.ws.connection_manager import connect, disconnect
from app.config.redis import publish
from app.services.chats import mark_chat_read
import json


router = APIRouter(
    prefix='/api/ws',
    tags=['ws'],
)


@router.websocket('/')
async def chat_websocket(ws: WebSocket, token: str = Query(...), connection_id: str = Query(...)):
    user_id = await verify_token(token)
    if not user_id:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with ws.app.state.pool.acquire() as conn:
        consented = await check_consent(conn, user_id)
    if not consented:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        await connect(user_id, connection_id, ws)
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
                        last_read_at = await mark_chat_read(conn, user_id, chat_id)
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
        await disconnect(user_id, connection_id)
