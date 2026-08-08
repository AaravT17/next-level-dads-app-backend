from uuid import UUID
from datetime import datetime
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Response
from app.dependencies.auth import get_current_user, get_admin_user
from app.dependencies.db import get_db
from app.models.organization_chats import (ChatResponse, SendMessageRequest, MessageResponse, LastMessageResponse, ChatListItemResponse)
from app.services import organization_chats as organization_chats_service

router = APIRouter(
    prefix="/api/organization-chats", tags=["Organization Messaging"]
)

@router.get('/', response_model=list[ChatListItemResponse])
async def list_chats(
    name: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_updated_at: datetime | None = Query(None),
    _admin: str = Depends(get_admin_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await organization_chats_service.list_chats(name=name, cursor_id=cursor_id, cursor_updated_at=cursor_updated_at, conn=conn)

@router.post("/{chat_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    chat_id: UUID,
    body: SendMessageRequest,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await organization_chats_service.send_message(chat_id=chat_id, body=body, user_id=UUID(user_id), conn=conn)

@router.get('/{chat_id}/messages', response_model=list[MessageResponse])
async def get_messages(
    chat_id: UUID,
    cursor_id: UUID | None = Query(None),
    cursor_created_at: datetime | None = Query(None),
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await organization_chats_service.get_messages(chat_id=chat_id, cursor_id=cursor_id, cursor_created_at=cursor_created_at, user_id=UUID(user_id), conn=conn)

# ── Admin Messaging  ─────────────────────────────────────────────

@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    return await organization_chats_service.get_organization_chat(chat_id=chat_id, conn=conn)
