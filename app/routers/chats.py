from fastapi import APIRouter, Depends, status, Query, Response
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
    EditMessageRequest,
    EditMessageResponse,
    ChatParticipantResponse,
    AddParticipantsRequest,
    ChatAddableParticipantResponse,
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
    # TODO: Support filtering by chat name, bearing in mind that for group chats, the name is the given name, but
    # for 1:1 chats, the name is the other participant's name, probably use a CASE statement or a CTE to unify this
    return await chats_service.get_chat_previews(conn, user_id, cursor_id, cursor_updated_at)


@router.post('/')
async def create_chat(
    body: CreateChatRequest,
    response: Response,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    result = await chats_service.create_chat(conn, user_id, body)
    response.status_code = status.HTTP_201_CREATED if result['created'] else status.HTTP_200_OK
    return {'id': result['id']}


@router.get('/{chat_id}', response_model=ChatResponse)
async def get_chat_preview(
    chat_id: UUID,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await chats_service.get_chat_preview(conn, user_id, chat_id)


# TODO: when a user opens a chat, update last_read_at in chat_participants and publish a chats:read event
# over the same pubsub channel so other tabs/devices for the same user can sync their unread state.
# unread indicator can then be derived from chat.updated_at > last_read_at in the chat preview query.


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


@router.patch('/{chat_id}/messages/{message_id}', response_model=EditMessageResponse)
async def edit_message(
    chat_id: UUID,
    message_id: UUID,
    body: EditMessageRequest,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await chats_service.edit_message(conn, user_id, chat_id, message_id, body)


@router.delete('/{chat_id}/messages/{message_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    chat_id: UUID,
    message_id: UUID,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    await chats_service.delete_message(conn, user_id, chat_id, message_id)


@router.get('/{chat_id}/participants', response_model=list[ChatParticipantResponse])
async def get_participants(
    chat_id: UUID,
    cursor_id: UUID | None = Query(None),
    cursor_joined_at: datetime | None = Query(None),
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await chats_service.get_participants(conn, user_id, chat_id, cursor_id, cursor_joined_at)


@router.post(
    '/{chat_id}/participants', response_model=list[ChatParticipantResponse], status_code=status.HTTP_201_CREATED
)
async def add_participants(
    chat_id: UUID,
    body: AddParticipantsRequest,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await chats_service.add_participants(conn, user_id, chat_id, body)


@router.delete('/{chat_id}/participants/me', status_code=status.HTTP_204_NO_CONTENT)
async def leave_chat(
    chat_id: UUID,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    await chats_service.leave_chat(conn, user_id, chat_id)


@router.delete('/{chat_id}/participants/{participant_id}', status_code=status.HTTP_204_NO_CONTENT)
async def remove_participant(
    chat_id: UUID,
    participant_id: UUID,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    await chats_service.remove_participant(conn, user_id, chat_id, participant_id)


@router.patch('/{chat_id}/participants/{participant_id}/promote', status_code=status.HTTP_204_NO_CONTENT)
async def promote_participant(
    chat_id: UUID,
    participant_id: UUID,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    await chats_service.promote_participant(conn, user_id, chat_id, participant_id)


@router.patch('/{chat_id}/participants/{participant_id}/demote', status_code=status.HTTP_204_NO_CONTENT)
async def demote_participant(
    chat_id: UUID,
    participant_id: UUID,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    await chats_service.demote_participant(conn, user_id, chat_id, participant_id)


@router.get('/{chat_id}/participants/addable', response_model=list[ChatAddableParticipantResponse])
async def get_addable_participants(
    chat_id: UUID,
    user_name: str | None = Query(None),
    cursor_id: UUID | None = Query(None),
    cursor_name: str | None = Query(None),
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await chats_service.get_addable_participants(conn, user_id, chat_id, user_name, cursor_id, cursor_name)


# TODO: Add an endpoint to update chat name, an endpoint to get chat details (name + list of participants)
# for the chat details screen, and an endpoint to update last_read_at for when a user opens a chat, which
# should also publish a chats:read event over the same pubsub channel so other tabs/devices for the same user
# can sync their unread state
