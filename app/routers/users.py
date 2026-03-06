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
from pydantic import Field
from postgrest import APIResponse, APIError
from typing import Annotated
from app.config.supabase import get_supabase
from app.config.constants import IMAGE_MIME_TO_EXT
from app.dependencies.auth import get_current_user
from app.models.users import UserResponse, UserProfile
from app.utils.interests import normalize_interest
from app.services.users import (
    build_discover_profiles_query,
    get_user_by_id,
    delete_avatar,
    resolve_connection_status,
)
from app.dependencies.db import get_db
import asyncpg
from datetime import datetime
from uuid import UUID


router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_curr_user(user_id: str = Depends(get_current_user)):
    try:
        user: dict | None = await get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
            )
        return user
    except HTTPException as _:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user data. Please try again later.",
        )


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
async def create_user(
    name: str = Form(...),
    age: Annotated[int, Field(ge=0)] = Form(...),
    city: str = Form(...),
    province: Annotated[str, Field(min_length=2, max_length=2)] = Form(...),
    about: str = Form(...),
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


@router.get("/", response_model=list[UserProfile])
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
            UserProfile(
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
