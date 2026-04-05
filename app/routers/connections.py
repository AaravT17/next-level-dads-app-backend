from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
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
from app.models.connections import (
    ConnectionCountResponse,
    ConnectionProfileResponse,
    ConnectionStatusResponse,
)
from app.utils.users import resolve_connection_status


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


@router.post(
    "/{user_id}",
    response_model=ConnectionStatusResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_connection_request(
    user_id: str,
    response: Response,
    curr_user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        user_id, curr_user_id = UUID(user_id), UUID(curr_user_id)
        query = """
            INSERT INTO connections (requesting_id, requested_id, status)
            VALUES ($1, $2, 'pending')
            ON CONFLICT DO NOTHING
            RETURNING requesting_id, status
        """
        res = await conn.fetchrow(query, *[curr_user_id, user_id])
        if not res:
            # fetch existing connection
            query = """
                SELECT requesting_id, status
                FROM connections
                WHERE (requesting_id = $1 AND requested_id = $2) OR (requesting_id = $2 AND requested_id = $1)
            """
            res = await conn.fetchrow(query, *[curr_user_id, user_id])
            if not res:
                # this should never happen
                raise Exception(
                    "Connection already exists (conflict occurred) but failed to fetch the existing connection."
                )
            response.status_code = status.HTTP_409_CONFLICT
            return {
                "connection_status": resolve_connection_status(
                    user_id=curr_user_id,
                    requesting_id=res["requesting_id"],
                    status=res["status"],
                )
            }
        else:
            return {
                "connection_status": resolve_connection_status(
                    user_id=curr_user_id,
                    requesting_id=res["requesting_id"],
                    status=res["status"],
                )
            }
    except HTTPException as _:
        raise
    except asyncpg.exceptions.CheckViolationError as _:
        # user tried to send a connection request to themselves
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot send a connection request to yourself.",
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send connection request. Please try again later.",
        )


@router.patch("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def accept_connection_request(
    user_id: str,
    curr_user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        user_id, curr_user_id = UUID(user_id), UUID(curr_user_id)
        query = """
            UPDATE connections
            SET status = 'accepted', updated_at = NOW()
            WHERE requesting_id = $1 AND requested_id = $2
            RETURNING requesting_id, status
        """
        res = await conn.fetchrow(query, *[user_id, curr_user_id])
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No pending connection request found from this user.",
            )
        return
    except HTTPException as _:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to accept connection request. Please try again later.",
        )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_connection(
    user_id: str,
    curr_user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        user_id, curr_user_id = UUID(user_id), UUID(curr_user_id)
        query = """
            DELETE FROM connections
            WHERE (requesting_id = $1 AND requested_id = $2) OR (requesting_id = $2 AND requested_id = $1)
        """
        await conn.execute(query, *[curr_user_id, user_id])
        return
    except HTTPException as _:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove connection. Please try again later.",
        )
