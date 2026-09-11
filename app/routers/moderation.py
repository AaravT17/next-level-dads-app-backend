from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from app.config.rate_limits import ReportContentLimiter, ReportUserLimiter, is_production

from app.dependencies.auth import get_consented_user
from app.dependencies.db import get_db
from app.moderation.models import (
    BanStatusResponse,
    NotificationResponse,
    ReportCreate,
    ReportResponse,
    UserReportCreate,
    UserReportResponse,
)
from app.moderation.repository import insert_user_report
from app.moderation.service import (
    get_active_ban,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    report_content,
)

router = APIRouter(
    prefix='/api/moderation',
    tags=['moderation'],
)


@router.post(
    '/reports',
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_consented_user), Depends(ReportContentLimiter())]
    if is_production()
    else [Depends(get_consented_user)],
)
async def create_report(
    payload: ReportCreate,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
):
    """Report a conversation, message or reply for manual review."""
    try:
        record = await report_content(
            conn,
            UUID(request.state.user_id),
            payload.content_type,
            payload.content_id,
            payload.reason,
        )
        return ReportResponse(**dict(record))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to submit report. Please try again later.',
        )


@router.get('/ban', response_model=BanStatusResponse)
async def get_my_ban(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    """Report whether the current user is under an active posting ban."""
    try:
        ban = await get_active_ban(conn, UUID(user_id))
        return BanStatusResponse(
            banned=ban is not None,
            expires_at=ban['expires_at'] if ban else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch ban status. Please try again later.',
        )


@router.get('/notifications', response_model=list[NotificationResponse])
async def get_notifications(
    unread_only: bool = Query(False),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    """List the current user's moderation notifications (newest first)."""
    try:
        records = await list_notifications(conn, UUID(user_id), unread_only)
        return [NotificationResponse(**dict(r)) for r in records]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch notifications. Please try again later.',
        )


@router.post(
    '/notifications/{notification_id}/read',
    status_code=status.HTTP_204_NO_CONTENT,
)
async def read_notification(
    notification_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    """Mark a single notification as read."""
    try:
        await mark_notification_read(conn, UUID(user_id), UUID(notification_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to update notification. Please try again later.',
        )


@router.post(
    '/notifications/read-all',
    status_code=status.HTTP_204_NO_CONTENT,
)
async def read_all_notifications(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    """Mark all of the current user's notifications as read."""
    try:
        await mark_all_notifications_read(conn, UUID(user_id))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to update notifications. Please try again later.',
        )


@router.post(
    '/user-reports',
    response_model=UserReportResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_consented_user), Depends(ReportUserLimiter())]
    if is_production()
    else [Depends(get_consented_user)],
)
async def create_user_report(
    payload: UserReportCreate,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
):
    """Report another user for review by admins."""
    user_id = request.state.user_id
    if str(payload.reported_id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='You cannot report yourself.',
        )
    try:
        record = await insert_user_report(
            conn,
            payload.reported_id,
            UUID(user_id),
            payload.reason,
        )
        return UserReportResponse(**dict(record))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to submit report. Please try again later.',
        )
