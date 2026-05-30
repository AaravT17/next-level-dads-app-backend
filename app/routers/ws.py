from fastapi import APIRouter, status, Query, WebSocket, WebSocketDisconnect
from app.utils.auth import verify_token
from app.ws.connection_manager import connect, disconnect


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

    try:
        await connect(user_id, connection_id, ws)
        while True:
            # keep the connection alive, we don't care about incoming messages, those are sent to server via
            # REST API rather than over WebSocket, so we can ignore any messages received here, but we need to
            # keep the connection open
            await ws.receive_text()
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
