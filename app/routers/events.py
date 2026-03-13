from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.dependencies.auth import get_current_user
from app.models.events import EventResponse
from app.dependencies.db import get_db
from typing import Literal
import asyncpg
from uuid import UUID
from datetime import datetime
from app.services.events import build_discover_events_query


router = APIRouter(
    prefix="/api/events",
    tags=["events"],
)


@router.get("/", response_model=list[EventResponse])
async def get_events(
    name: str | None = None,
    event_type: Literal["local", "virtual"] | None = Query(default=None, alias="type"),
    is_free: bool | None = None,
    cursor_id: str | None = None,
    cursor_created_at: datetime | None = None,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_discover_events_query(
            user_id=UUID(user_id),
            name=name,
            event_type=event_type,
            is_free=is_free,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_created_at=cursor_created_at,
        )
        res = await conn.fetch(query, *params)
        return [EventResponse(**dict(r)) for r in res]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch events. Please try again later.",
        )
