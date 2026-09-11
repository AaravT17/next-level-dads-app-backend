from fastapi import APIRouter, Depends, status, Query, Request, Response
from app.common.config.constants import IS_PRODUCTION
from app.common.dependencies.rate_limiting import SendConnectionRequestLimiter
from app.common.dependencies.auth import get_consented_user
from app.common.dependencies.db import get_db
import asyncpg
import app.modules.connections.service as connections_service
from uuid import UUID
from datetime import datetime
from app.modules.connections.models import (
    ConnectionProfileResponse,
    ConnectionStatusResponse,
)


router = APIRouter(
    prefix='/api/connections',
    tags=['connections'],
)


@router.get('/connected', response_model=list[ConnectionProfileResponse])
async def get_connections(
    name: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_updated_at: datetime | None = Query(None),
    user_id: str = Depends(get_consented_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await connections_service.get_connections(conn, user_id, name, cursor_id, cursor_updated_at)


@router.get('/requests', response_model=list[ConnectionProfileResponse])
async def get_incoming_requests(
    name: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_updated_at: datetime | None = Query(None),
    user_id: str = Depends(get_consented_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await connections_service.get_incoming_requests(conn, user_id, name, cursor_id, cursor_updated_at)


@router.get('/requested', response_model=list[ConnectionProfileResponse])
async def get_outgoing_requests(
    name: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_updated_at: datetime | None = Query(None),
    user_id: str = Depends(get_consented_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await connections_service.get_outgoing_requests(conn, user_id, name, cursor_id, cursor_updated_at)


@router.post(
    '/{target_user_id}',
    response_model=ConnectionStatusResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_consented_user), Depends(SendConnectionRequestLimiter())]
    if IS_PRODUCTION
    else [Depends(get_consented_user)],
)
async def send_connection_request(
    target_user_id: UUID,
    request: Request,
    response: Response,
    conn: asyncpg.Connection = Depends(get_db),
):
    result, created = await connections_service.send_connection_request(conn, UUID(request.state.user_id), target_user_id)
    if not created:
        response.status_code = status.HTTP_409_CONFLICT
    return result


@router.patch('/{from_user_id}', status_code=status.HTTP_204_NO_CONTENT)
async def accept_connection_request(
    from_user_id: UUID,
    curr_user_id: str = Depends(get_consented_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    await connections_service.accept_connection_request(conn, from_user_id, UUID(curr_user_id))


@router.delete('/{target_user_id}', status_code=status.HTTP_204_NO_CONTENT)
async def remove_connection(
    target_user_id: UUID,
    curr_user_id: str = Depends(get_consented_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    await connections_service.remove_connection(conn, UUID(curr_user_id), target_user_id)
