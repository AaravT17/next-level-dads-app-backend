from fastapi import APIRouter, Depends, status, Query
from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
import asyncpg
from datetime import datetime
from uuid import UUID
from app.models.chats import (
    CreateChatRequest,
    ChatResponse,
    MessageResponse,
    SendMessageRequest,
)
import app.services.chats as chats_service

router = APIRouter(
    prefix='/api/chats',
    tags=['chats'],
)


@router.get('/', response_model=list[ChatResponse])
async def get_chat_previews(
    cursor_id: UUID | None = Query(None),
    cursor_updated_at: datetime | None = Query(None),
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await chats_service.get_chat_previews(conn, user_id, cursor_id, cursor_updated_at)


@router.post('/', status_code=status.HTTP_201_CREATED)
async def create_chat(
    body: CreateChatRequest,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await chats_service.create_chat(conn, user_id, body)


@router.get('/{chat_id}', response_model=ChatResponse)
async def get_chat_preview(
    chat_id: UUID,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await chats_service.get_chat_preview(conn, user_id, chat_id)


@router.get('/{chat_id}/messages', response_model=list[MessageResponse])
async def get_chat_messages(
    chat_id: UUID,
    cursor_id: UUID | None = Query(None),
    cursor_created_at: datetime | None = Query(None),
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await chats_service.get_messages(conn, user_id, chat_id, cursor_id, cursor_created_at)


@router.post('/{chat_id}/messages', response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    chat_id: UUID,
    body: SendMessageRequest,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await chats_service.send_message(conn, user_id, chat_id, body)


@router.patch('/{chat_id}/messages/{message_id}')
async def edit_message(chat_id: UUID, message_id: UUID):
    raise NotImplementedError('Editing messages is not implemented yet')


@router.delete('/{chat_id}/messages/{message_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(chat_id: UUID, message_id: UUID):
    raise NotImplementedError('Deleting messages is not implemented yet')


@router.get('/{chat_id}/participants')
async def get_participants(chat_id: UUID):
    raise NotImplementedError('Getting chat participants is not implemented yet')


@router.post('/{chat_id}/participants', status_code=status.HTTP_201_CREATED)
async def add_participant(chat_id: UUID):
    raise NotImplementedError('Adding chat participants is not implemented yet')


@router.delete('/{chat_id}/participants/{participant_id}', status_code=status.HTTP_204_NO_CONTENT)
async def remove_participant(chat_id: UUID, participant_id: UUID):
    raise NotImplementedError('Removing chat participants is not implemented yet')


@router.patch('/{chat_id}/participants/{participant_id}')
async def update_participant(chat_id: UUID, participant_id: UUID):
    raise NotImplementedError('Updating chat participants is not implemented yet')
