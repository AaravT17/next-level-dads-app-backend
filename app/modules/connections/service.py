from datetime import datetime
from uuid import UUID
import asyncpg
from fastapi import HTTPException, status
from app.common.config.constants import (
    PROFILES_PAGE_LIMIT,
)
from app.modules.connections.models import (
    ConnectionProfileResponse,
    ConnectionStatusResponse,
)
from app.modules.connections.utils import resolve_connection_status


async def get_connections(
    conn: asyncpg.Connection,
    user_id: str,
    name: str | None,
    cursor_id: UUID | None,
    cursor_updated_at: datetime | None,
) -> list[ConnectionProfileResponse]:
    try:
        query, params = _build_get_connections_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=cursor_id,
            cursor_updated_at=cursor_updated_at,
        )
        res = await conn.fetch(query, *params)
        return [ConnectionProfileResponse(**dict(r)) for r in res]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch connections. Please try again later.',
        )


async def get_incoming_requests(
    conn: asyncpg.Connection,
    user_id: str,
    name: str | None,
    cursor_id: UUID | None,
    cursor_updated_at: datetime | None,
) -> list[ConnectionProfileResponse]:
    try:
        query, params = _build_get_incoming_requests_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=cursor_id,
            cursor_updated_at=cursor_updated_at,
        )
        res = await conn.fetch(query, *params)
        return [ConnectionProfileResponse(**dict(r)) for r in res]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch connection requests. Please try again later.',
        )


async def get_outgoing_requests(
    conn: asyncpg.Connection,
    user_id: str,
    name: str | None,
    cursor_id: UUID | None,
    cursor_updated_at: datetime | None,
) -> list[ConnectionProfileResponse]:
    try:
        query, params = _build_get_outgoing_requests_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=cursor_id,
            cursor_updated_at=cursor_updated_at,
        )
        res = await conn.fetch(query, *params)
        return [ConnectionProfileResponse(**dict(r)) for r in res]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch requested connections. Please try again later.',
        )


async def send_connection_request(
    conn: asyncpg.Connection,
    curr_user_id: UUID,
    target_user_id: UUID,
    note: str | None = None,
) -> tuple[ConnectionStatusResponse, bool]:
    """
    Sends a connection request from the current user to the target user and returns (connection_status, created).
    If created=False, there is already a connection request or a connection between the two users, and the existing
    status is returned.
    """
    try:
        res = await conn.fetchrow(
            """
            INSERT INTO connections (requesting_id, requested_id, status, note)
            VALUES ($1, $2, 'pending', $3)
            ON CONFLICT DO NOTHING
            RETURNING requesting_id, status
            """,
            curr_user_id,
            target_user_id,
            note,
        )

        if not res:
            res = await conn.fetchrow(
                """
                SELECT requesting_id, status
                FROM connections
                WHERE (requesting_id = $1 AND requested_id = $2) OR (requesting_id = $2 AND requested_id = $1)
                """,
                curr_user_id,
                target_user_id,
            )
            if not res:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail='Failed to send connection request. Please try again later.',
                )
            return ConnectionStatusResponse(
                connection_status=resolve_connection_status(
                    user_id=curr_user_id,
                    requesting_id=res['requesting_id'],
                    connection_status=res['status'],
                )
            ), False

        return ConnectionStatusResponse(
            connection_status=resolve_connection_status(
                user_id=curr_user_id,
                requesting_id=res['requesting_id'],
                connection_status=res['status'],
            )
        ), True
    except HTTPException:
        raise
    except asyncpg.exceptions.CheckViolationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='You cannot send a connection request to yourself.',
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to send connection request. Please try again later.',
        )


async def accept_connection_request(
    conn: asyncpg.Connection,
    from_user_id: UUID,
    curr_user_id: UUID,
):
    """Accept a pending request addressed to the caller.

    The status predicate matters twice. `unique_pair` means one row per pair, so
    without it this also matches a 'blocked' row and would turn the accept
    endpoint into an unblock the moment a block feature exists. It also stops an
    already-accepted row being re-stamped: `updated_at` is the sort key for
    get_connections, so a repeated PATCH would otherwise let anyone push
    themselves to the top of someone else's connection list and disturb that
    list's keyset cursor mid-page.
    """
    try:
        res = await conn.fetchrow(
            """
            UPDATE connections
            SET status = 'accepted', updated_at = NOW()
            WHERE requesting_id = $1 AND requested_id = $2 AND status = 'pending'
            RETURNING requesting_id, status
            """,
            from_user_id,
            curr_user_id,
        )
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='No pending connection request found from this user.',
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to accept connection request. Please try again later.',
        )


async def remove_connection(
    conn: asyncpg.Connection,
    curr_user_id: UUID,
    target_user_id: UUID,
):
    try:
        await conn.execute(
            """
            WITH remove_connection AS (
                DELETE FROM connections
                WHERE (requesting_id = $1 AND requested_id = $2) OR (requesting_id = $2 AND requested_id = $1)
            )
            DELETE FROM chats
            WHERE type = 'dm'
            AND (
                (dm_user_1 = $1 AND dm_user_2 = $2) OR
                (dm_user_1 = $2 AND dm_user_2 = $1)
            )
            """,
            curr_user_id,
            target_user_id,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to remove connection. Please try again later.',
        )


def _build_get_connections_query(
    user_id: UUID,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_updated_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = []
    params = [user_id]
    i = 2

    if name:
        conditions.append(f'u.name ILIKE ${i}')
        params.append(f'%{name}%')
        i += 1

    if cursor_updated_at and cursor_id:
        conditions.append(f'(c.updated_at, c.connection_id) < (${i}, ${i + 1})')
        params.extend([cursor_updated_at, cursor_id])
        i += 2

    where_clause = f'WHERE {" AND ".join(conditions)}' if conditions else ''
    query = f"""
        SELECT c.connection_id, c.updated_at AS connection_updated_at, 'connected' AS connection_status, u.*
        FROM (
            SELECT
                id AS connection_id,
                updated_at,
                CASE WHEN requesting_id = $1 THEN requested_id ELSE requesting_id END AS user_id,
                status
            FROM connections
            WHERE status = 'accepted'
              AND (requesting_id = $1 OR requested_id = $1)
        ) c
        JOIN user_profiles u ON u.id = c.user_id
        {where_clause}
        ORDER BY c.updated_at DESC, c.connection_id DESC
        LIMIT ${i}
    """
    params.append(PROFILES_PAGE_LIMIT)

    return query, params


def _build_get_incoming_requests_query(
    user_id: UUID,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_updated_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = ['requested_id = $1', "status = 'pending'"]
    params = [user_id]
    i = 2

    if name:
        conditions.append(f'u.name ILIKE ${i}')
        params.append(f'%{name}%')
        i += 1

    if cursor_updated_at and cursor_id:
        conditions.append(f'(c.updated_at, c.id) < (${i}, ${i + 1})')
        params.extend([cursor_updated_at, cursor_id])
        i += 2

    where_clause = ' AND '.join(conditions)
    query = f"""
        SELECT u.*, c.id AS connection_id, c.updated_at AS connection_updated_at, c.note, 'pending_incoming' AS connection_status
        FROM connections c
        JOIN user_profiles u ON u.id = c.requesting_id
        WHERE {where_clause}
        ORDER BY c.updated_at DESC, c.id DESC
        LIMIT ${i}
    """
    params.append(PROFILES_PAGE_LIMIT)

    return query, params


def _build_get_outgoing_requests_query(
    user_id: UUID,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_updated_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = ['requesting_id = $1', "status = 'pending'"]
    params = [user_id]
    i = 2

    if name:
        conditions.append(f'u.name ILIKE ${i}')
        params.append(f'%{name}%')
        i += 1

    if cursor_updated_at and cursor_id:
        conditions.append(f'(c.updated_at, c.id) < (${i}, ${i + 1})')
        params.extend([cursor_updated_at, cursor_id])
        i += 2

    where_clause = ' AND '.join(conditions)
    query = f"""
        SELECT u.*, c.id AS connection_id, c.updated_at AS connection_updated_at, c.note, 'pending_outgoing' AS connection_status
        FROM connections c
        JOIN user_profiles u ON u.id = c.requested_id
        WHERE {where_clause}
        ORDER BY c.updated_at DESC, c.id DESC
        LIMIT ${i}
    """
    params.append(PROFILES_PAGE_LIMIT)

    return query, params
