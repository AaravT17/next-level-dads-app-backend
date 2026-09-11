from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.dependencies.auth import get_consented_user
from app.models.events import EventResponse
from app.dependencies.db import get_db
from typing import Literal
import asyncpg
from uuid import UUID
from datetime import datetime
from app.services.events import build_discover_events_query, build_get_event_by_id_query


router = APIRouter(
    prefix='/api/events',
    tags=['events'],
)


@router.get('/', response_model=list[EventResponse])
async def get_events(
    name: str | None = None,
    event_type: Literal['local', 'virtual'] | None = Query(default=None, alias='type'),
    is_free: bool | None = None,
    cursor_id: str | None = None,
    cursor_starts_at: datetime | None = None,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        query, params = build_discover_events_query(
            user_id=UUID(user_id),
            name=name,
            event_type=event_type,
            is_free=is_free,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_starts_at=cursor_starts_at,
        )
        res = await conn.fetch(query, *params)
        return [EventResponse(**dict(r)) for r in res]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch events. Please try again later.',
        )


@router.get('/{id}', response_model=EventResponse)
async def get_event_by_id(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        query, params = build_get_event_by_id_query(id=UUID(id), user_id=UUID(user_id))
        res = await conn.fetchrow(query, *params)
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Event not found')
        return EventResponse(**dict(res))
    except HTTPException as _:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch event details. Please try again later.',
        )


@router.post('/{id}/attendees', status_code=status.HTTP_204_NO_CONTENT)
async def register_for_event(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    # TODO: For paid events, integrate with payment gateway and only register user after successful payment
    try:
        id, user_id = UUID(id), UUID(user_id)
        # check if the event is free or paid
        query = """
            SELECT price_cad from events WHERE id = $1
        """
        res = await conn.fetchval(query, *[id], column=0)
        if res is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Event not found')
        price = float(res)
        # for now, if the event is paid, do not allow registration through this endpoint
        if price > 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Cannot register for paid events through this endpoint.',
            )
        query = """
            INSERT INTO event_attendees (event_id, user_id, joined_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT DO NOTHING
        """
        await conn.execute(query, *[id, user_id])
        return
    except HTTPException as _:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to register for event. Please try again later.',
        )


@router.delete('/{id}/attendees', status_code=status.HTTP_204_NO_CONTENT)
async def unregister_from_event(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        id, user_id = UUID(id), UUID(user_id)
        query = """
            DELETE FROM event_attendees 
            WHERE event_id = $1 AND user_id = $2
        """
        await conn.execute(query, *[id, user_id])
        return
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to unregister from event. Please try again later.',
        )
