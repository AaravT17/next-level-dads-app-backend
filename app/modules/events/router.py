from fastapi import APIRouter, Depends, Query, status
from app.common.dependencies.auth import get_consented_user
from app.common.dependencies.db import get_db
from app.modules.events.models import EventResponse
import app.modules.events.service as events_service
from typing import Literal
import asyncpg
from datetime import datetime


router = APIRouter(
    prefix='/api/events',
    tags=['events'],
)


@router.get('/', response_model=list[EventResponse])
async def discover_events(
    name: str | None = None,
    event_type: Literal['local', 'virtual'] | None = Query(default=None, alias='type'),
    is_free: bool | None = None,
    cursor_id: str | None = None,
    cursor_starts_at: datetime | None = None,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    return await events_service.discover_events(conn, user_id, name, event_type, is_free, cursor_id, cursor_starts_at)


@router.get('/{id}', response_model=EventResponse)
async def get_event(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    return await events_service.get_event(conn, id, user_id)


@router.post('/{id}/attendees', status_code=status.HTTP_204_NO_CONTENT)
async def register_for_event(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    await events_service.register_for_event(conn, id, user_id)


@router.delete('/{id}/attendees', status_code=status.HTTP_204_NO_CONTENT)
async def unregister_from_event(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    await events_service.unregister_from_event(conn, id, user_id)
