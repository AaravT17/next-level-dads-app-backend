from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
    Body,
    status,
    Request,
)
from app.common.config.constants import IS_PRODUCTION, MAX_NAME_LENGTH, MAX_CITY_LENGTH, MAX_BIO_LENGTH
from app.common.dependencies.rate_limiting import (
    CreateProfileLimiter,
    DiscoverProfilesLimiter,
    UpdateAvatarLimiter,
    UpdateProfileLimiter,
)
from app.common.dependencies.auth import get_current_user, get_consented_user
from app.modules.users.models import MeResponse, UserProfileResponse, UserStatsResponse, UpdatePreferencesRequest
from app.modules.communities.models import CommunityResponse
from app.modules.events.models import EventResponse
import app.modules.users.service as users_service
from app.common.dependencies.db import get_db
import asyncpg
from datetime import datetime, date
from uuid import UUID
import app.modules.communities.service as communities_service
import app.modules.events.service as events_service


router = APIRouter(prefix='/api/users', tags=['users'])


@router.get('/me', response_model=MeResponse)
async def get_me(conn: asyncpg.Connection = Depends(get_db), user_id: str = Depends(get_current_user)):
    return await users_service.get_me(conn, user_id)


@router.get('/{id}', response_model=UserProfileResponse)
async def get_user_profile(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    return await users_service.get_user_profile(conn, id, user_id)


@router.post(
    '/',
    status_code=status.HTTP_201_CREATED,
    response_model=MeResponse,
    dependencies=[Depends(get_current_user), Depends(CreateProfileLimiter())]
    if IS_PRODUCTION
    else [Depends(get_current_user)],
)
async def create_profile(
    request: Request,
    name: str = Form(..., max_length=MAX_NAME_LENGTH),
    date_of_birth: date = Form(...),
    city: str = Form(..., max_length=MAX_CITY_LENGTH),
    province: str = Form(..., min_length=2, max_length=2),
    about: str = Form(..., max_length=MAX_BIO_LENGTH),
    avatar: UploadFile | None = File(None),
    interests: list[str] | None = Form(None),
    children_age_ranges: list[str] = Form(...),
    accepted_terms: bool = Form(...),
    accepted_privacy_policy: bool = Form(...),
    marketing_emails_opt_in: bool = Form(False),
    conn: asyncpg.Connection = Depends(get_db),
):
    user_id = request.state.user_id

    file_contents: bytes | None = None
    mime_type: str | None = None
    if avatar:
        file_contents = await avatar.read()
        mime_type = avatar.content_type

    return await users_service.create_profile(
        conn,
        user_id,
        name,
        date_of_birth,
        city,
        province,
        about,
        file_contents,
        mime_type,
        interests,
        children_age_ranges,
        marketing_emails_opt_in,
        accepted_terms,
        accepted_privacy_policy,
    )


@router.get(
    '/',
    response_model=list[UserProfileResponse],
    dependencies=[Depends(get_consented_user), Depends(DiscoverProfilesLimiter())]
    if IS_PRODUCTION
    else [Depends(get_consented_user)],
)
async def discover_profiles(
    request: Request,
    interests: list[str] | None = Query(None),
    children_age_ranges: list[str] | None = Query(None),
    provinces: list[str] | None = Query(None),
    age_ranges: list[str] | None = Query(None),
    name: str | None = Query(None),
    cursor_id: str | None = Query(None),
    cursor_created_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await users_service.discover_profiles(
        conn, request.state.user_id, interests, children_age_ranges,
        provinces, age_ranges, name, cursor_id, cursor_created_at,
    )


@router.get('/me/communities', response_model=list[CommunityResponse])
async def get_user_communities(
    name: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_created_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    return await communities_service.get_user_communities(conn, user_id, name, cursor_id, cursor_created_at)


@router.get('/me/events', response_model=list[EventResponse])
async def get_user_events(
    name: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_starts_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    return await events_service.get_user_events(conn, user_id, name, cursor_id, cursor_starts_at)


@router.patch(
    '/me',
    response_model=MeResponse,
    dependencies=[Depends(get_consented_user), Depends(UpdateProfileLimiter())]
    if IS_PRODUCTION
    else [Depends(get_consented_user)],
)
async def update_profile(
    request: Request,
    name: str = Body(..., max_length=MAX_NAME_LENGTH),
    date_of_birth: date = Body(...),
    city: str = Body(..., max_length=MAX_CITY_LENGTH),
    province: str = Body(..., min_length=2, max_length=2),
    about: str = Body(..., max_length=MAX_BIO_LENGTH),
    interests: list[str] | None = Body(None),
    children_age_ranges: list[str] = Body(...),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await users_service.update_profile(
        conn, request.state.user_id, name, date_of_birth,
        city, province, about, interests, children_age_ranges,
    )


@router.put(
    '/me/avatar',
    dependencies=[Depends(get_consented_user), Depends(UpdateAvatarLimiter())]
    if IS_PRODUCTION
    else [Depends(get_consented_user)],
)
async def update_avatar(
    request: Request,
    avatar: UploadFile = File(...),
    conn: asyncpg.Connection = Depends(get_db),
):
    file_contents = await avatar.read()
    mime_type = avatar.content_type
    avatar_url = await users_service.update_avatar(conn, request.state.user_id, file_contents, mime_type)
    return {'avatar_url': avatar_url}


@router.delete('/me/avatar', status_code=status.HTTP_204_NO_CONTENT)
async def delete_avatar(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    await users_service.delete_avatar(conn, user_id)


@router.delete('/me', status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str = Depends(get_consented_user),
):
    await users_service.delete_user(user_id)


@router.get('/me/stats', response_model=UserStatsResponse)
async def get_user_stats(
    user_id: str = Depends(get_consented_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await users_service.get_user_stats(conn, user_id)


@router.post('/me/legal-acceptances', status_code=status.HTTP_204_NO_CONTENT)
async def accept_legal_documents(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    await users_service.accept_legal_documents(conn, user_id)


@router.patch('/me/preferences', status_code=status.HTTP_204_NO_CONTENT)
async def update_preferences(
    body: UpdatePreferencesRequest,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    await users_service.update_preferences(conn, user_id, body.marketing_emails_opt_in)
