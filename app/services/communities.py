from datetime import datetime
from uuid import UUID
from app.config.constants import DISCOVER_COMMUNITIES_PAGE_LIMIT


def build_discover_communities_query(
    user_id: UUID,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_created_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = [
        "c.id NOT IN (SELECT community_id FROM community_members WHERE user_id = $1)"
    ]
    params = [user_id]
    i = 2

    if name:
        conditions.append(f"c.name ILIKE ${i}")
        params.append(f"%{name}%")
        i += 1

    if cursor_created_at and cursor_id:
        conditions.append(f"(c.created_at, c.id) < (${i}, ${i + 1})")
        params.extend([cursor_created_at, cursor_id])
        i += 2

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT c.*, 
        EXISTS (SELECT 1 FROM community_members cm WHERE cm.community_id = c.id AND cm.user_id = $1) AS is_member,
        (SELECT cm.role FROM community_members cm WHERE cm.community_id = c.id AND cm.user_id = $1) AS role
        FROM communities c
        WHERE {where_clause}
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ${i}
    """
    params.append(DISCOVER_COMMUNITIES_PAGE_LIMIT)

    return query, params
