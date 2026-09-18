from datetime import datetime
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.common.dependencies.auth import get_consented_user
from app.common.dependencies.db import get_db

import app.modules.notifications.service as notifications_service
from app.modules.notifications.models import NotificationCountResponse, NotificationResponse

router = APIRouter(
    prefix='/api/notifications',
    tags=['notifications'],
)


@router.get('', response_model=list[NotificationResponse])
async def get_notifications(
    cursor_created_at: datetime | None = Query(None),
    cursor_id: UUID | None = Query(None),
    user_id: str = Depends(get_consented_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await notifications_service.get_notifications(conn, user_id, cursor_created_at, cursor_id)


@router.get('/count', response_model=NotificationCountResponse)
async def get_unread_count(
    user_id: str = Depends(get_consented_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await notifications_service.get_unread_count(conn, user_id)
