from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    File,
    Form,
    UploadFile,
)
from fastapi.params import Query
from postgrest import APIResponse, APIError
from app.config.supabase import get_supabase
from app.config.constants import (
    IMAGE_MIME_TO_EXT,
    MAX_NAME_LENGTH,
    MAX_CITY_LENGTH,
    MAX_BIO_LENGTH,
)
from app.dependencies.auth import get_current_user
from app.models.users import UserResponse, UserProfileResponse
from app.models.communities import CommunityResponse
from app.models.events import EventResponse
from app.utils.interests import normalize_interest
from app.services.users import (
    build_discover_profiles_query,
    build_get_user_by_id_query,
    delete_avatar,
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
    supabase = get_supabase()
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
            await supabase.storage.from_("avatars").upload(
                path=file_path,
                file=file_contents,
                file_options={"content-type": mime_type, "upsert": "true"},
            )
            avatar_url = await supabase.storage.from_("avatars").get_public_url(
                file_path
            )
        except Exception as _:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload avatar. Please try again later.",
            )

    normalized_interests = (
        [normalize_interest(i) for i in interests] if interests else []
    )
    try:
        res: APIResponse = await supabase.rpc(
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
        if avatar_url:
            await delete_avatar(user_id)
        if e.code == "23505":  # uniqueness violation
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User already exists.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user. Please try again later.",
        )
    except Exception as _:
        if avatar_url:
            await delete_avatar(user_id)
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
