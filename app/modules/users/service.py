import json
import asyncpg
from fastapi import HTTPException, status
from app.common.config.supabase import get_supabase_admin
from app.common.utils.errors import value_error_to_http
from app.common.config.constants import AGE_RANGES, IMAGE_MIME_TO_EXT, PROFILES_PAGE_LIMIT
from app.modules.users.models import MeResponse, UserProfileResponse, UserStatsResponse
from app.modules.connections.utils import resolve_connection_status
from app.modules.interests.utils import normalize_interest
from datetime import date, datetime
from uuid import UUID
from app.modules.users.utils import is_18_or_older


async def get_me(conn: asyncpg.Connection, user_id: str) -> MeResponse:
    try:
        query, params = _build_get_me_query(user_id=user_id)
        res = await conn.fetchrow(query, *params)
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found.')
        data = dict(res)
        data['preferences'] = json.loads(data['preferences'])
        data['legal_acceptances'] = json.loads(data['legal_acceptances'])
        return MeResponse(**data)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch user. Please try again later.',
        )


async def get_user_profile(conn: asyncpg.Connection, user_id: str, curr_user_id: str) -> UserProfileResponse:
    try:
        query, params = _build_get_user_profile_query(user_id=user_id, curr_user_id=curr_user_id)
        res = await conn.fetchrow(query, *params)
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found.')
        return UserProfileResponse(
            **{k: v for k, v in dict(res).items() if k not in ('requesting_id', 'connection_status')},
            connection_status=resolve_connection_status(
                UUID(curr_user_id),
                res['requesting_id'],
                res['connection_status'],
            ),
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch user. Please try again later.',
        )


async def create_profile(
    conn: asyncpg.Connection,
    user_id: str,
    name: str,
    date_of_birth: date,
    city: str,
    province: str,
    about: str,
    file_contents: bytes | None,
    mime_type: str | None,
    interests: list[str] | None,
    children_age_ranges: list[str],
    marketing_emails_opt_in: bool,
    accepted_terms: bool,
    accepted_privacy_policy: bool,
) -> MeResponse:
    if not accepted_terms or not accepted_privacy_policy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='You must accept the Terms of Service and Privacy Policy to create an account.',
        )
    if not is_18_or_older(date_of_birth):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='You must be 18 or older to create an account.',
        )

    avatar_url: str | None = None
    if file_contents and mime_type:
        avatar_url = await _upload_avatar_to_storage(user_id, file_contents, mime_type)

    try:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO users (id, name, date_of_birth, city, province, about, avatar_url)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                UUID(user_id),
                name,
                date_of_birth,
                city,
                province,
                about,
                avatar_url,
            )
            if interests is not None:
                normalized_interests = [normalize_interest(i) for i in interests]
                res = await conn.fetch(
                    """
                    INSERT INTO interests (name)
                    SELECT unnest($1::text[])
                    ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id, name
                    """,
                    normalized_interests,
                )
                interest_ids = [r['id'] for r in res]
                await conn.execute(
                    """
                    INSERT INTO user_interests (user_id, interest_id)
                    SELECT $1, unnest($2::uuid[])
                    """,
                    UUID(user_id),
                    interest_ids,
                )
            await conn.execute(
                """
                INSERT INTO user_children (user_id, age_range)
                SELECT $1, unnest($2::text[])
                """,
                UUID(user_id),
                children_age_ranges,
            )
            await conn.execute(
                """
                INSERT INTO user_preferences (user_id, marketing_emails_opt_in)
                VALUES ($1, $2)
                """,
                UUID(user_id),
                marketing_emails_opt_in,
            )
            # TODO: Remove community guidelines from legal acceptances, only T&C and privacy policy are required
            await conn.execute(
                """
                INSERT INTO user_legal_acceptances (user_id, document_type)
                VALUES ($1, 'terms'), ($1, 'privacy_policy'), ($1, 'community_guidelines')
                """,
                UUID(user_id),
            )
            return await get_me(conn, user_id)
    except asyncpg.exceptions.UniqueViolationError:
        if avatar_url:
            await _delete_avatar_from_storage(user_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='User already exists.',
        )
    except HTTPException:
        raise
    except Exception:
        if avatar_url:
            await _delete_avatar_from_storage(user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to create user. Please try again later.',
        )


async def discover_profiles(
    conn: asyncpg.Connection,
    user_id: str,
    interests: list[str] | None,
    children_age_ranges: list[str] | None,
    provinces: list[str] | None,
    age_ranges: list[str] | None,
    name: str | None,
    cursor_id: str | None,
    cursor_created_at: datetime | None,
) -> list[UserProfileResponse]:
    try:
        uid = UUID(user_id)
        query, params = _build_discover_profiles_query(
            user_id=uid,
            interests=interests,
            children_age_ranges=children_age_ranges,
            provinces=provinces,
            age_ranges=age_ranges,
            name=name,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_created_at=cursor_created_at,
        )
        res = await conn.fetch(query, *params)
        return [
            UserProfileResponse(
                **{k: v for k, v in dict(r).items() if k not in ('requesting_id', 'connection_status')},
                connection_status=resolve_connection_status(uid, r['requesting_id'], r['connection_status']),
            )
            for r in res
        ]
    except ValueError as e:
        raise value_error_to_http(e, 'Failed to fetch profiles. Please try again later.')
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch profiles. Please try again later.',
        )


async def update_profile(
    conn: asyncpg.Connection,
    user_id: str,
    name: str,
    date_of_birth,
    city: str,
    province: str,
    about: str,
    interests: list[str] | None,
    children_age_ranges: list[str],
) -> MeResponse:
    if not is_18_or_older(date_of_birth):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='You must be 18 or older.',
        )
    try:
        async with conn.transaction():
            await conn.execute(
                """
                DELETE FROM user_interests WHERE user_id = $1
                """,
                UUID(user_id),
            )
            if interests is not None:
                normalized_interests = [normalize_interest(i) for i in interests]
                res = await conn.fetch(
                    """
                    INSERT INTO interests (name)
                    SELECT unnest($1::text[])
                    ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id, name
                    """,
                    normalized_interests,
                )
                interest_ids = [r['id'] for r in res]
                await conn.execute(
                    """
                    INSERT INTO user_interests (user_id, interest_id)
                    SELECT $1, unnest($2::uuid[])
                    """,
                    UUID(user_id),
                    interest_ids,
                )
            await conn.execute(
                """
                DELETE FROM user_children WHERE user_id = $1
                """,
                UUID(user_id),
            )
            await conn.execute(
                """
                INSERT INTO user_children (user_id, age_range)
                SELECT $1, unnest($2::text[])
                """,
                UUID(user_id),
                children_age_ranges,
            )
            await conn.execute(
                """
                UPDATE users
                SET name = $1, date_of_birth = $2, city = $3, province = $4, about = $5, updated_at = NOW()
                WHERE id = $6
                """,
                name,
                date_of_birth,
                city,
                province,
                about,
                UUID(user_id),
            )
            return await get_me(conn, user_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to update profile. Please try again later.',
        )


async def update_avatar(conn: asyncpg.Connection, user_id: str, file_contents: bytes, mime_type: str | None) -> str:
    try:
        avatar_url = await _upload_avatar_to_storage(user_id, file_contents, mime_type)
        await conn.execute(
            """
            UPDATE users SET avatar_url = $1 WHERE id = $2
            """,
            avatar_url,
            UUID(user_id),
        )
        return avatar_url
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to update avatar. Please try again later.',
        )


async def delete_avatar(conn: asyncpg.Connection, user_id: str):
    try:
        await conn.execute(
            """
            UPDATE users SET avatar_url = NULL WHERE id = $1
            """,
            UUID(user_id),
        )
        await _delete_avatar_from_storage(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to delete avatar. Please try again later.',
        )


async def delete_user(user_id: str):
    supabase_admin = get_supabase_admin()
    try:
        await supabase_admin.auth.admin.delete_user(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to delete account. Please try again later.',
        )
    await _delete_avatar_from_storage(user_id)


async def get_user_stats(conn: asyncpg.Connection, user_id: str) -> UserStatsResponse:
    try:
        res = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM connections WHERE status = 'accepted'
                    AND (requesting_id = $1 OR requested_id = $1)) AS connections,
                (SELECT COUNT(*) FROM connections WHERE status = 'pending' AND requested_id = $1) AS requests,
                (SELECT COUNT(*) FROM community_members WHERE user_id = $1) AS communities_joined,
                (SELECT COUNT(*) FROM event_attendees WHERE user_id = $1) AS events_registered_for
            """,
            UUID(user_id),
        )
        return UserStatsResponse(**dict(res))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch user stats. Please try again later.',
        )


async def accept_legal_documents(conn: asyncpg.Connection, user_id: str):
    try:
        await conn.execute(
            """
            INSERT INTO user_legal_acceptances (user_id, document_type)
            VALUES ($1, 'terms'), ($1, 'privacy_policy')
            ON CONFLICT (user_id, document_type) DO UPDATE SET accepted_at = NOW()
            """,
            UUID(user_id),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to record legal acceptances. Please try again later.',
        )


async def update_preferences(conn: asyncpg.Connection, user_id: str, marketing_emails_opt_in: bool):
    try:
        await conn.execute(
            """
            UPDATE user_preferences
            SET marketing_emails_opt_in = $1, updated_at = NOW()
            WHERE user_id = $2
            """,
            marketing_emails_opt_in,
            UUID(user_id),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to update preferences. Please try again later.',
        )


def _build_get_me_query(user_id: str) -> tuple[str, list]:
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


def _build_get_user_profile_query(user_id: str, curr_user_id: str) -> tuple[str, list]:
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


def _build_discover_profiles_query(
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


async def _upload_avatar_to_storage(user_id: str, file_contents: bytes, mime_type: str | None) -> str:
    """Validate mime type, upload avatar to Supabase storage, and return the public URL."""
    if not mime_type or mime_type not in IMAGE_MIME_TO_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Invalid avatar image type. Supported types: PNG, JPG, JPEG.',
        )
    supabase_admin = get_supabase_admin()
    try:
        await supabase_admin.storage.from_('avatars').upload(
            path=user_id,
            file=file_contents,
            file_options={'content-type': mime_type, 'upsert': 'true'},
        )
        # TODO: There is a small chance that the upload succeeds but the public URL retrieval fails. We should 
        # handle this case and delete the uploaded file if the public URL retrieval fails. However, in that case,
        # the issue is that we might delete the user's old file if they are updating their avatar, and this may
        # leave a dangling reference in the DB. We need to think about how to handle this properly. Best approach
        # may be to use random UUIDs for the file path (or perhaps /user_id/avatar_uuid) so that we can delete the 
        # file if the public URL retrieval fails.
        return await supabase_admin.storage.from_('avatars').get_public_url(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to upload avatar. Please try again later.',
        )


async def _delete_avatar_from_storage(user_id: str):
    supabase_admin = get_supabase_admin()
    try:
        await supabase_admin.storage.from_('avatars').remove([user_id])
    except Exception:
        # TODO: Log the exception
        pass
