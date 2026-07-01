from app.config.supabase import get_supabase_admin
from app.config.constants import AGE_RANGES, PROFILES_PAGE_LIMIT
from datetime import datetime
from uuid import UUID


def build_get_me_query(user_id: str) -> tuple[str, list]:
    params = [user_id]
    query = """
        SELECT
            up.*,
            u.is_admin,
            json_build_object(
                'marketing_emails_opt_in', COALESCE(pref.marketing_emails_opt_in, FALSE)
            )::jsonb AS preferences,
            json_build_object(
                'terms', EXISTS(
                    SELECT 1 FROM user_legal_acceptances ula
                    WHERE ula.user_id = up.id AND ula.document_type = 'terms'
                ),
                'privacy_policy', EXISTS(
                    SELECT 1 FROM user_legal_acceptances ula
                    WHERE ula.user_id = up.id AND ula.document_type = 'privacy_policy'
                )
            )::jsonb AS legal_acceptances
        FROM user_profiles up
        JOIN public.users u ON u.id = up.id
        LEFT JOIN user_preferences pref ON pref.user_id = up.id
        WHERE up.id = $1
    """
    return query, params


def build_get_user_profile_query(user_id: str, curr_user_id: str) -> tuple[str, list]:
    params = [user_id, curr_user_id]
    query = """
        SELECT u.*, c.requesting_id, c.status AS connection_status
        FROM user_profiles u
        LEFT JOIN connections c ON (
            (c.requesting_id = $2 AND c.requested_id = u.id) OR
            (c.requested_id = $2 AND c.requesting_id = u.id)
        )
        WHERE u.id = $1
    """
    return query, params


async def delete_avatar_from_storage(user_id: str):
    supabase_admin = get_supabase_admin()
    try:
        await supabase_admin.storage.from_('avatars').remove([user_id])
    except Exception as _:
        # add proper logging here
        pass


def build_discover_profiles_query(
    user_id: UUID,
    interests: list[str] | None = None,
    children_age_ranges: list[str] | None = None,
    provinces: list[str] | None = None,
    age_ranges: list[str] | None = None,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_created_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = ['u.id != $1']
    params = [user_id]
    i = 2

    if name:
        conditions.append(f'u.name ILIKE ${i}')
        params.append(f'%{name}%')
        i += 1

    if provinces:
        conditions.append(f'u.province = ANY(${i}::text[])')
        params.append(provinces)
        i += 1

    if age_ranges:
        range_conditions = []
        for r in age_ranges:
            min_age, max_age = AGE_RANGES.get(r, (None, None))
            if min_age is None or max_age is None:
                raise ValueError(f'Invalid age range: {r}')
            range_conditions.append(f'(u.age >= ${i} AND u.age <= ${i + 1})')
            params.extend([min_age, max_age])
            i += 2
        conditions.append(f'({" OR ".join(range_conditions)})')

    if interests:
        conditions.append(f'u.interests && ${i}::text[]')
        params.append(interests)
        i += 1

    if children_age_ranges:
        conditions.append(f'u.children && ${i}::text[]')
        params.append(children_age_ranges)
        i += 1

    if cursor_created_at and cursor_id:
        conditions.append(f'(u.created_at, u.id) < (${i}, ${i + 1})')
        params.extend([cursor_created_at, cursor_id])
        i += 2

    where_clause = "(c.id IS NULL OR (c.requesting_id = $1 AND c.status = 'pending')) AND "

    where_clause += ' AND '.join(conditions)
    query = f"""
        SELECT u.*, c.requesting_id, c.status AS connection_status
        FROM user_profiles u
        LEFT JOIN connections c ON (
            (c.requesting_id = $1 AND c.requested_id = u.id) OR
            (c.requested_id = $1 AND c.requesting_id = u.id)
        )
        WHERE {where_clause}
        ORDER BY u.created_at DESC, u.id DESC
        LIMIT ${i}
    """
    params.append(PROFILES_PAGE_LIMIT)

    return query, params
