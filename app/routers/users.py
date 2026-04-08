from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    File,
    Form,
    UploadFile,
    Body,
    Query,
)
from postgrest import APIResponse, APIError
from app.config.supabase import get_supabase_admin
from app.config.constants import (
    IMAGE_MIME_TO_EXT,
    MAX_NAME_LENGTH,
    MAX_CITY_LENGTH,
    MAX_BIO_LENGTH,
)
from app.dependencies.auth import get_current_user
from app.models.users import UserResponse, UserProfileResponse, UserStatsResponse
from app.models.communities import CommunityResponse
from app.models.events import EventResponse
from app.utils.interests import normalize_interest
from app.services.users import (
    build_discover_profiles_query,
    build_get_user_by_id_query,
    delete_avatar_from_storage,
)
from app.utils.users import resolve_connection_status
from app.dependencies.db import get_db
import asyncpg
from datetime import datetime
from uuid import UUID
from app.services.communities import build_user_communities_query
from app.services.events import build_user_events_query


router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_curr_user(
    conn: asyncpg.Connection = Depends(get_db), user_id: str = Depends(get_current_user)
):
    try:
        query, params = build_get_user_by_id_query(user_id=user_id)
        res = await conn.fetchrow(query, *params)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
            )
        return UserResponse(**res)
    except HTTPException as _:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user. Please try again later.",
        )


@router.get("/{id}", response_model=UserProfileResponse)
async def get_user(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_get_user_by_id_query(user_id=id, curr_user_id=user_id)
        res = await conn.fetchrow(query, *params)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
            )
        return UserProfileResponse(
            **{
                k: v
                for k, v in dict(res).items()
                if k not in ("requesting_id", "connection_status")
            },
            connection_status=resolve_connection_status(
                UUID(user_id),
                res["requesting_id"],
                res["connection_status"],
            ),
        )
    except HTTPException as _:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user. Please try again later.",
        )


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
async def create_user(
    name: str = Form(..., max_length=MAX_NAME_LENGTH),
    age: int = Form(..., ge=0, le=200),
    city: str = Form(..., max_length=MAX_CITY_LENGTH),
    province: str = Form(..., min_length=2, max_length=2),
    about: str = Form(..., max_length=MAX_BIO_LENGTH),
    avatar: UploadFile | None = File(None),
    interests: list[str] | None = Form(None),
    children_age_ranges: list[str] = Form(...),
    user_id: str = Depends(get_current_user),
):
    supabase_admin = get_supabase_admin()
    avatar_url: str | None = None
    if avatar:
        mime_type = avatar.content_type
        if not mime_type or mime_type not in IMAGE_MIME_TO_EXT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid avatar image type. Supported types: PNG, JPG, JPEG.",
            )
        file_path = user_id
        file_contents = await avatar.read()
        try:
            await supabase_admin.storage.from_("avatars").upload(
                path=file_path,
                file=file_contents,
                file_options={"content-type": mime_type, "upsert": "true"},
            )
            avatar_url = await supabase_admin.storage.from_("avatars").get_public_url(
                file_path
            )
        except Exception as e:
            print(f"Exception in avatar upload: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload avatar. Please try again later.",
            )

    normalized_interests = (
        [normalize_interest(i) for i in interests] if interests else []
    )
    try:
        res: APIResponse = await supabase_admin.rpc(
            "create_user_profile",
            {
                "p_user_id": user_id,
                "p_name": name,
                "p_age": age,
                "p_city": city,
                "p_province": province,
                "p_about": about,
                "p_avatar_url": avatar_url,
                "p_interests": normalized_interests,
                "p_children": children_age_ranges,
            },
        ).execute()
        return res.data
    except APIError as e:
        print(f"APIError in create_user: {e}")
        if avatar_url:
            await delete_avatar_from_storage(user_id)
        if e.code == "23505":  # uniqueness violation
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User already exists.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user. Please try again later.",
        )
    except Exception as e:
        print(f"Exception in create_user: {e}")
        if avatar_url:
            await delete_avatar_from_storage(user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user. Please try again later.",
        )


@router.get("/", response_model=list[UserProfileResponse])
async def get_discover_profiles(
    interests: list[str] | None = Query(None),
    children_age_ranges: list[str] | None = Query(None),
    provinces: list[str] | None = Query(None),
    age_ranges: list[str] | None = Query(None),
    cursor_id: str | None = Query(None),
    cursor_created_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        uid = UUID(user_id)
        query, params = build_discover_profiles_query(
            user_id=uid,
            interests=interests,
            children_age_ranges=children_age_ranges,
            provinces=provinces,
            age_ranges=age_ranges,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_created_at=cursor_created_at,
        )
        res = await conn.fetch(query, *params)
        profiles = [
            UserProfileResponse(
                **{
                    k: v
                    for k, v in dict(r).items()
                    if k not in ("requesting_id", "connection_status")
                },
                connection_status=resolve_connection_status(
                    uid, r["requesting_id"], r["connection_status"]
                ),
            )
            for r in res
        ]
        return profiles
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch profiles. Please try again later.",
        )


@router.get("/me/communities", response_model=list[CommunityResponse])
async def get_user_communities(
    name: str | None = Query(None),
    cursor_id: str | None = Query(None),
    cursor_created_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_user_communities_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_created_at=cursor_created_at,
        )
        res = await conn.fetch(query, *params)
        return [CommunityResponse(**r) for r in res]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch communities. Please try again later.",
        )


@router.get("/me/events", response_model=list[EventResponse])
async def get_user_events(
    name: str | None = Query(None),
    cursor_id: str | None = Query(None),
    cursor_starts_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_user_events_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_starts_at=cursor_starts_at,
        )
        res = await conn.fetch(query, *params)
        return [EventResponse(**r) for r in res]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch events. Please try again later.",
        )


@router.patch("/me", response_model=UserResponse)
async def update_user(
    name: str = Body(..., max_length=MAX_NAME_LENGTH),
    age: int = Body(..., ge=0, le=200),
    city: str = Body(..., max_length=MAX_CITY_LENGTH),
    province: str = Body(..., min_length=2, max_length=2),
    about: str = Body(..., max_length=MAX_BIO_LENGTH),
    interests: list[str] | None = Body(None),
    children_age_ranges: list[str] = Body(...),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        # perform the profile update in a transaction to ensure atomicity of operations
        async with conn.transaction():
            # delete existing interests for the user
            delete_query = """
                DELETE FROM user_interests WHERE user_id = $1
            """
            await conn.execute(delete_query, *[UUID(user_id)])
            normalized_interests = []
            if interests is not None:
                # normalize interests
                normalized_interests = [normalize_interest(i) for i in interests]
                # insert the interests into the user_interests table and get the resulting interest IDs
                query = """
                    INSERT INTO interests (name)
                    SELECT unnest($1::text[])
                    ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id, name
                """
                res = await conn.fetch(query, *[normalized_interests])
                interest_ids = [r["id"] for r in res]
                # insert into user_interests table
                query = """
                    INSERT INTO user_interests (user_id, interest_id)
                    SELECT $1, unnest($2::uuid[])
                """
                await conn.execute(query, *[UUID(user_id), interest_ids])

            # update the children's ages in the user_profiles table
            # first, delete existing rows
            query = """
                DELETE FROM user_children WHERE user_id = $1
            """
            await conn.execute(query, *[UUID(user_id)])
            # then, insert new rows for each age range
            query = """
                INSERT INTO user_children (user_id, age_range)
                SELECT $1, unnest($2::text[])
            """
            await conn.execute(query, *[UUID(user_id), children_age_ranges])
            # finally, update the rest of the profile fields in the user_profiles table
            query = """
                UPDATE users
                SET name = $1, age = $2, city = $3, province = $4, about = $5, updated_at = NOW()
                WHERE id = $6
                RETURNING *
            """
            res = await conn.fetchrow(
                query,
                *[name, age, city, province, about, UUID(user_id)],
            )
            if not res:
                # this should never happen since the user must exist to reach this endpoint, but we add this check just in case
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
                )
            return UserResponse(
                **res,
                interests=normalized_interests,
                children=children_age_ranges,
            )
    except HTTPException as _:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile. Please try again later.",
        )


@router.put("/me/avatar")
async def update_avatar(
    avatar: UploadFile = File(...),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    supabase_admin = get_supabase_admin()
    mime_type = avatar.content_type
    if not mime_type or mime_type not in IMAGE_MIME_TO_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid avatar image type. Supported types: PNG, JPG, JPEG.",
        )
    file_path = user_id
    file_contents = await avatar.read()
    try:
        await supabase_admin.storage.from_("avatars").upload(
            path=file_path,
            file=file_contents,
            file_options={"content-type": mime_type, "upsert": "true"},
        )
        avatar_url = await supabase_admin.storage.from_("avatars").get_public_url(
            file_path
        )
        query = """
            UPDATE users SET avatar_url = $1 WHERE id = $2
        """
        await conn.execute(query, *[avatar_url, UUID(user_id)])
        return {"avatar_url": avatar_url}
    except HTTPException as _:
        raise
    except Exception as e:
        print(f"Exception in avatar upload: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update avatar. Please try again later.",
        )


@router.delete("/me/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def delete_avatar(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        # set avatar_url to NULL in DB before deleting from storage to prevent broken image links in case storage deletion succeeds but DB update fails
        query = """
            UPDATE users SET avatar_url = NULL WHERE id = $1
        """
        await conn.execute(query, *[UUID(user_id)])
        await delete_avatar_from_storage(user_id)
    except HTTPException as _:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete avatar. Please try again later.",
        )


@router.get("/me/stats", response_model=UserStatsResponse)
async def get_user_stats(
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        query = """
            SELECT
                (SELECT COUNT(*) FROM connections WHERE status = 'accepted' 
                    AND (requesting_id = $1 OR requested_id = $1)) AS connections,
                (SELECT COUNT(*) FROM connections WHERE status = 'pending' AND requested_id = $1) AS requests,
                (SELECT COUNT(*) FROM community_members WHERE user_id = $1) AS communities_joined,
                (SELECT COUNT(*) FROM event_attendees WHERE user_id = $1) AS events_registered_for
        """
        res = await conn.fetchrow(query, UUID(user_id))
        return UserStatsResponse(**dict(res))
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user stats. Please try again later.",
        )
