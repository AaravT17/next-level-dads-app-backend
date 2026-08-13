from uuid import UUID
from datetime import datetime
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Response
from app.dependencies.auth import get_current_user, get_admin_user
from app.dependencies.db import get_db
from app.models.organization_chats import (ChatResponse, SendMessageRequest, MessageResponse, LastMessageResponse, ChatListItemResponse)
from app.services import organization_chats as organization_chats_service

router = APIRouter(prefix="/api/organization-chats", tags=["Organization Messaging"])

# ── Partner Messaging ─────────────────────────────────────────────

@router.get('/me', response_model=ChatResponse)
async def get_my_chat(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query = """
            SELECT oc.id, oc.organization_id, o.name AS organization_name, oc.created_at, oc.updated_at
            FROM organization_chats oc
            JOIN organizations o ON o.id = oc.organization_id
            JOIN organization_representatives r ON r.organization_id = oc.organization_id
            WHERE r.user_id = $1
        """
        res = await conn.fetchrow(query, UUID(user_id))
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No chat found.')
        return ChatResponse(**dict(res))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch chat. Please try again later.',
        )

# ── Shared Messaging ─────────────────────────────────────────────

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

@router.get('/', response_model=list[ChatListItemResponse])
async def list_chats(
    search: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_updated_at: datetime | None = Query(None),
    _admin: str = Depends(get_admin_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await organization_chats_service.list_chats(
        search=search, cursor_id=cursor_id, cursor_updated_at=cursor_updated_at, conn=conn
    )


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    return await organization_chats_service.get_organization_chat(chat_id=chat_id, conn=conn)


@router.get("/organizations/{organization_id}/chat", response_model=ChatResponse)
async def get_chat_by_organization(
    organization_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    return await organization_chats_service.get_chat_by_organization(organization_id=organization_id, conn=conn)