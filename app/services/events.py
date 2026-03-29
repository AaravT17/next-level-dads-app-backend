from uuid import UUID
from datetime import datetime
from app.config.constants import EVENTS_PAGE_LIMIT
from typing import Literal


def build_discover_events_query(
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


def build_user_events_query(
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


def build_get_event_by_id_query(
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
