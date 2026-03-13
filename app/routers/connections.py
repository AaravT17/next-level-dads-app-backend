from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
import asyncpg
from app.services.connections import (
    build_connected_query,
    build_requests_query,
    build_requested_query,
)
from uuid import UUID
from datetime import datetime
from app.models.connections import ConnectionCountResponse, ConnectionProfileResponse


router = APIRouter(
    prefix="/api/connections",
    tags=["connections"],
)


@router.get("/count", response_model=ConnectionCountResponse)
async def get_connection_counts(
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        query = """
            SELECT
                COUNT(*) FILTER (WHERE status = 'accepted' AND (requesting_id = $1 OR requested_id = $1)) AS connections,
                COUNT(*) FILTER (WHERE status = 'pending' AND requested_id = $1) AS requests
            FROM connections
        """
        res = await conn.fetchrow(query, UUID(user_id))
        return ConnectionCountResponse(**dict(res))
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch connection data. Please try again later.",
        )


@router.get("/connected", response_model=list[ConnectionProfileResponse])
async def get_connected(
    name: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_updated_at: datetime | None = Query(None),
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        query, params = build_connected_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=cursor_id,
            cursor_updated_at=cursor_updated_at,
        )
        res = await conn.fetch(query, *params)
        return [ConnectionProfileResponse(**dict(r)) for r in res]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch connections. Please try again later.",
        )


@router.get("/requests", response_model=list[ConnectionProfileResponse])
async def get_requests(
    name: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_updated_at: datetime | None = Query(None),
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        query, params = build_requests_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=cursor_id,
            cursor_updated_at=cursor_updated_at,
        )
        res = await conn.fetch(query, *params)
        return [ConnectionProfileResponse(**dict(r)) for r in res]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch connection requests. Please try again later.",
        )


@router.get("/requested", response_model=list[ConnectionProfileResponse])
async def get_requested(
    name: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_updated_at: datetime | None = Query(None),
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        query, params = build_requested_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=cursor_id,
            cursor_updated_at=cursor_updated_at,
        )
        res = await conn.fetch(query, *params)
        return [ConnectionProfileResponse(**dict(r)) for r in res]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch requested connections. Please try again later.",
        )
