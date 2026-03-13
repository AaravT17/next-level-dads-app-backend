from datetime import datetime
from uuid import UUID
from app.config.constants import (
    CONNECTED_PAGE_LIMIT,
    REQUESTED_PAGE_LIMIT,
    REQUESTS_PAGE_LIMIT,
)


def build_connected_query(
    user_id: UUID,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_updated_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = []
    params = [user_id]
    i = 2

    if name:
        conditions.append(f"u.name ILIKE ${i}")
        params.append(f"%{name}%")
        i += 1

    if cursor_updated_at and cursor_id:
        conditions.append(f"(c.updated_at, c.connection_id) < (${i}, ${i + 1})")
        params.extend([cursor_updated_at, cursor_id])
        i += 2

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
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
    params.append(CONNECTED_PAGE_LIMIT)

    return query, params


def build_requests_query(
    user_id: UUID,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_updated_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = ["requested_id = $1", "status = 'pending'"]
    params = [user_id]
    i = 2

    if name:
        conditions.append(f"u.name ILIKE ${i}")
        params.append(f"%{name}%")
        i += 1

    if cursor_updated_at and cursor_id:
        conditions.append(f"(c.updated_at, c.id) < (${i}, ${i + 1})")
        params.extend([cursor_updated_at, cursor_id])
        i += 2

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT u.*, c.id AS connection_id, c.updated_at AS connection_updated_at, 'pending_incoming' AS connection_status
        FROM connections c
        JOIN user_profiles u ON u.id = c.requesting_id
        WHERE {where_clause}
        ORDER BY c.updated_at DESC, c.id DESC
        LIMIT ${i}
    """
    params.append(REQUESTS_PAGE_LIMIT)

    return query, params


def build_requested_query(
    user_id: UUID,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_updated_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = ["requesting_id = $1", "status = 'pending'"]
    params = [user_id]
    i = 2

    if name:
        conditions.append(f"u.name ILIKE ${i}")
        params.append(f"%{name}%")
        i += 1

    if cursor_updated_at and cursor_id:
        conditions.append(f"(c.updated_at, c.id) < (${i}, ${i + 1})")
        params.extend([cursor_updated_at, cursor_id])
        i += 2

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT u.*, c.id AS connection_id, c.updated_at AS connection_updated_at, 'pending_outgoing' AS connection_status
        FROM connections c
        JOIN user_profiles u ON u.id = c.requested_id
        WHERE {where_clause}
        ORDER BY c.updated_at DESC, c.id DESC
        LIMIT ${i}
    """
    params.append(REQUESTED_PAGE_LIMIT)

    return query, params
