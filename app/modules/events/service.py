from uuid import UUID
from datetime import datetime
from typing import Literal

import asyncpg
from fastapi import HTTPException, status

from app.common.config.constants import EVENTS_PAGE_LIMIT
from app.modules.events.models import EventResponse


async def discover_events(
    conn: asyncpg.Connection,
    user_id: str,
    name: str | None,
    event_type: Literal['local', 'virtual'] | None,
    is_free: bool | None,
    cursor_id: str | None,
    cursor_starts_at: datetime | None,
) -> list[EventResponse]:
    try:
        query, params = _build_discover_events_query(
            user_id=UUID(user_id),
            name=name,
            event_type=event_type,
            is_free=is_free,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_starts_at=cursor_starts_at,
        )
        res = await conn.fetch(query, *params)
        return [EventResponse(**dict(r)) for r in res]
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid request parameters.')
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch events. Please try again later.',
        )


async def get_event(
    conn: asyncpg.Connection,
    event_id: UUID,
    user_id: str,
) -> EventResponse:
    try:
        query, params = _build_get_event_query(id=event_id, user_id=UUID(user_id))
        res = await conn.fetchrow(query, *params)
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Event not found')
        return EventResponse(**dict(res))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch event details. Please try again later.',
        )


async def register_for_event(
    conn: asyncpg.Connection,
    event_id: UUID,
    user_id: str,
):
    # TODO: Implement registration for paid events.
    try:
        user_id = UUID(user_id)
        res = await conn.fetchval(
            """
            SELECT price_cad from events WHERE id = $1
            """,
            event_id,
            column=0,
        )
        if res is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Event not found')
        price = float(res)
        if price > 0:
            # Registering for paid events is yet to be implemented.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Cannot register for paid events through this endpoint.',
            )
        await conn.execute(
            """
            INSERT INTO event_attendees (event_id, user_id, joined_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT DO NOTHING
            """,
            event_id,
            user_id,
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to register for event. Please try again later.',
        )


async def unregister_from_event(
    conn: asyncpg.Connection,
    event_id: UUID,
    user_id: str,
):
    try:
        user_id = UUID(user_id)
        await conn.execute(
            """
            DELETE FROM event_attendees
            WHERE event_id = $1 AND user_id = $2
            """,
            event_id,
            user_id,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to unregister from event. Please try again later.',
        )


async def get_user_events(
    conn: asyncpg.Connection,
    user_id: str,
    name: str | None,
    cursor_id: UUID | None,
    cursor_starts_at: datetime | None,
) -> list[EventResponse]:
    try:
        query, params = _build_get_user_events_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=cursor_id,
            cursor_starts_at=cursor_starts_at,
        )
        res = await conn.fetch(query, *params)
        return [EventResponse(**dict(r)) for r in res]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch events. Please try again later.',
        )


# --- Private helpers ---


def _build_discover_events_query(
    user_id: UUID,
    name: str | None = None,
    event_type: Literal["local", "virtual"] | None = None,
    is_free: bool | None = None,
    cursor_id: UUID | None = None,
    cursor_starts_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = [
        "NOT EXISTS (SELECT 1 FROM event_attendees ea WHERE ea.event_id = e.id AND ea.user_id = $1)",
        "e.starts_at >= NOW()",
    ]
    params = [user_id]
    i = 2

    if name:
        conditions.append(f"e.name ILIKE ${i}")
        params.append(f"%{name}%")
        i += 1

    if event_type:
        conditions.append(f"e.type = ${i}")
        params.append(event_type)
        i += 1

    if is_free is not None:
        if is_free:
            conditions.append("e.price_cad = 0")
        else:
            conditions.append("e.price_cad > 0")

    if cursor_starts_at and cursor_id:
        conditions.append(f"(e.starts_at, e.id) > (${i}, ${i + 1})")
        params.extend([cursor_starts_at, cursor_id])
        i += 2

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT e.*,
        (SELECT COUNT(*) FROM event_attendees ea WHERE ea.event_id = e.id) AS attendee_count,
        FALSE AS is_attending
        FROM events e
        WHERE {where_clause}
        ORDER BY e.starts_at ASC, e.id ASC
        LIMIT ${i}
    """
    params.append(EVENTS_PAGE_LIMIT)

    return query, params


def _build_get_user_events_query(
    user_id: UUID,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_starts_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = ["ea.user_id = $1"]
    params = [user_id]
    i = 2

    if name:
        conditions.append(f"e.name ILIKE ${i}")
        params.append(f"%{name}%")
        i += 1

    if cursor_starts_at and cursor_id:
        conditions.append(f"(e.starts_at, e.id) > (${i}, ${i + 1})")
        params.extend([cursor_starts_at, cursor_id])
        i += 2

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT e.*,
        (SELECT COUNT(*) FROM event_attendees ea WHERE ea.event_id = e.id) AS attendee_count,
        TRUE AS is_attending
        FROM events e
        JOIN event_attendees ea ON ea.event_id = e.id
        WHERE {where_clause}
        ORDER BY e.starts_at ASC, e.id ASC
        LIMIT ${i}
    """
    params.append(EVENTS_PAGE_LIMIT)

    return query, params


def _build_get_event_query(
    id: UUID,
    user_id: UUID,
) -> tuple[str, list]:
    query = """
        SELECT e.*,
        (SELECT COUNT(*) FROM event_attendees ea WHERE ea.event_id = e.id) AS attendee_count,
        (CASE WHEN ea.user_id IS NOT NULL THEN TRUE ELSE FALSE END) AS is_attending
        FROM events e
        LEFT JOIN event_attendees ea ON ea.event_id = e.id AND ea.user_id = $2
        WHERE e.id = $1
    """
    params = [id, user_id]
    return query, params
