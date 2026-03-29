from datetime import datetime
from uuid import UUID
from app.config.constants import COMMUNITIES_PAGE_LIMIT, PROFILES_PAGE_LIMIT


def build_discover_communities_query(
    user_id: UUID,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_created_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = [
        "NOT EXISTS (SELECT 1 FROM community_members cm WHERE cm.community_id = c.id AND cm.user_id = $1)"
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
        (SELECT COUNT(*) FROM community_members cm WHERE cm.community_id = c.id) AS member_count,
        FALSE AS is_member, NULL AS role
        FROM communities c
        WHERE {where_clause}
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ${i}
    """
    params.append(COMMUNITIES_PAGE_LIMIT)

    return query, params


def build_user_communities_query(
    user_id: UUID,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_created_at: datetime | None = None,
) -> tuple[str, list]:
    i = 2
    conditions = ["cm.user_id = $1"]
    params = [user_id]

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
        (SELECT COUNT(*) FROM community_members cm WHERE cm.community_id = c.id) AS member_count, cm.role, TRUE AS is_member
        FROM communities c
        JOIN community_members cm ON c.id = cm.community_id
        WHERE {where_clause}
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ${i}
    """
    params.append(COMMUNITIES_PAGE_LIMIT)

    return query, params


def build_get_community_by_id_query(id: UUID, user_id: UUID) -> tuple[str, list]:
    query = """
        SELECT c.*,
        (SELECT COUNT(*) FROM community_members cm WHERE cm.community_id = c.id) AS member_count,
        cm.role, (CASE WHEN cm.user_id IS NOT NULL THEN TRUE ELSE FALSE END) AS is_member
        FROM communities c
        LEFT JOIN community_members cm ON c.id = cm.community_id AND cm.user_id = $2
        WHERE c.id = $1
    """
    params = [id, user_id]
    return query, params


def build_get_community_members_query(
    id: UUID,
    cursor_id: UUID | None = None,
    cursor_joined_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = ["cm.community_id = $1"]
    params = [id]
    i = 2

    if cursor_joined_at and cursor_id:
        conditions.append(f"(cm.joined_at, cm.user_id) < (${i}, ${i + 1})")
        params.extend([cursor_joined_at, cursor_id])
        i += 2

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT u.*, cm.joined_at, cm.role
        FROM user_profiles u
        JOIN community_members cm ON u.id = cm.user_id
        WHERE {where_clause}
        ORDER BY cm.joined_at DESC, cm.user_id DESC
        LIMIT ${i}
    """
    params.append(PROFILES_PAGE_LIMIT)

    return query, params
