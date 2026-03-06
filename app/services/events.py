from uuid import UUID
from datetime import datetime
from app.config.constants import DISCOVER_EVENTS_PAGE_LIMIT
from typing import Literal


def build_discover_events_query(
    user_id: UUID,
    name: str | None = None,
    event_type: Literal["local", "virtual"] | None = None,
    is_free: bool | None = None,
    cursor_id: UUID | None = None,
    cursor_created_at: datetime | None = None,
) -> list[dict]:
    conditions = [
        "e.id NOT IN (SELECT event_id FROM event_attendees WHERE user_id = $1)"
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

    if cursor_created_at and cursor_id:
        conditions.append(f"(e.created_at, e.id) < (${i}, ${i + 1})")
        params.extend([cursor_created_at, cursor_id])
        i += 2

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT e.*, EXISTS (SELECT 1 FROM event_attendees ea WHERE ea.event_id = e.id AND ea.user_id = $1) AS is_attending
        FROM events e
        WHERE {where_clause}
        ORDER BY e.created_at DESC, e.id DESC
        LIMIT ${i}
    """
    params.append(DISCOVER_EVENTS_PAGE_LIMIT)

    return query, params
