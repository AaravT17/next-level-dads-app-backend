from fastapi import APIRouter, Depends, status, HTTPException, Query
from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
import asyncpg
from datetime import datetime
from uuid import UUID
from app.models.chats import (
    CreateChatRequest,
    ChatResponse,
    LastMessageResponse,
    OtherUserResponse,
    MessageResponse,
    ReplyToResponse,
    SendMessageRequest,
)
from app.services.chats import build_get_chat_previews_query, build_get_chat_preview_query, build_get_messages_query
from app.config.redis import publish

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
    query, params = build_get_chat_previews_query(user_id, cursor_id, cursor_updated_at)
    try:
        rows = await conn.fetch(query, *params)
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch chats. Please try again later.',
        )

    chats = []
    for r in rows:
        last_message = None
        if r['last_message_id'] is not None:
            last_message = LastMessageResponse(
                id=r['last_message_id'],
                content=r['last_message_content'],
                sender_id=r['last_message_sender_id'],
                sender_name=r['last_message_sender_name'],
                created_at=r['last_message_created_at'],
                is_deleted=r['last_message_is_deleted'],
            )

        other_user = None
        if r['other_user_id'] is not None:
            other_user = OtherUserResponse(
                id=r['other_user_id'],
                name=r['other_user_name'],
                avatar_url=r['other_user_avatar_url'],
            )

        chats.append(
            ChatResponse(
                id=r['id'],
                type=r['type'],
                name=r['name'],
                updated_at=r['updated_at'],
                last_message=last_message,
                other_user=other_user,
            )
        )

    return chats


@router.post('/', status_code=status.HTTP_201_CREATED)
async def create_chat(
    body: CreateChatRequest,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    name, participant_ids = body.name, body.participant_ids
    # validate the participant IDs: they must exist, be connected with the current user, and not include the current
    # user (checking that they are connected with the current user also implicitly checks that they exist, since you
    # can't be connected with a non-existent user, and that they do not include the current user, since you can't be
    # connected with yourself)
    try:
        connections = await conn.fetch(
            """
            SELECT
                (CASE WHEN requesting_id = $1 THEN requested_id ELSE requesting_id END) AS user_id
            FROM connections
            WHERE (requesting_id = $1 OR requested_id = $1) AND status = 'accepted'
            """,
            *[user_id],
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to create chat. Please try again later.',
        )

    s = set(r['user_id'] for r in connections)
    if any(pid not in s for pid in participant_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid participant IDs')

    # input validation complete, create the chat and the corresponding chat_participants entries

    if len(participant_ids) == 1:
        # create a DM chat
        try:
            async with conn.transaction():
                chat_id = await conn.fetchval(
                    """
                    INSERT INTO chats (type, dm_user_1, dm_user_2)
                    VALUES ('dm', $1, $2)
                    RETURNING id
                    """,
                    *[user_id, participant_ids[0]],
                )
                await conn.executemany(
                    """
                    INSERT INTO chat_participants (chat_id, user_id)
                    VALUES ($1, $2)
                    """,
                    [(chat_id, user_id), (chat_id, participant_ids[0])],
                )
                # being admin does not make sense or matter for DM chats
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='A DM chat with this user already exists')
        except Exception as _:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to create chat. Please try again later.',
            )
    else:
        # create a group chat
        try:
            async with conn.transaction():
                chat_id = await conn.fetchval(
                    """
                    INSERT INTO chats (type, name)
                    VALUES ('group', $1)
                    RETURNING id
                    """,
                    *[name],
                )
                await conn.executemany(
                    """
                    INSERT INTO chat_participants (chat_id, user_id, is_admin)
                    VALUES ($1, $2, $3)
                    """,
                    [(chat_id, pid, False) for pid in participant_ids] + [(chat_id, user_id, True)],
                )
        except Exception as _:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to create chat. Please try again later.',
            )
    return {'id': str(chat_id)}


@router.get('/{chat_id}', response_model=ChatResponse)
async def get_chat_preview(
    chat_id: UUID,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    query, params = build_get_chat_preview_query(user_id, chat_id)
    try:
        r = await conn.fetchrow(query, *params)
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch chat. Please try again later.',
        )

    if r is None:
        # if the query returns no rows, it means either the chat doesn't exist or the user is not a participant in
        # the chat, we don't want to reveal which of these is the case, so we return a generic 404 error
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')

    last_message = None
    if r['last_message_id'] is not None:
        last_message = LastMessageResponse(
            id=r['last_message_id'],
            content=r['last_message_content'],
            sender_id=r['last_message_sender_id'],
            sender_name=r['last_message_sender_name'],
            created_at=r['last_message_created_at'],
            is_deleted=r['last_message_is_deleted'],
        )

    other_user = None
    if r['other_user_id'] is not None:
        other_user = OtherUserResponse(
            id=r['other_user_id'],
            name=r['other_user_name'],
            avatar_url=r['other_user_avatar_url'],
        )

    return ChatResponse(
        id=r['id'],
        type=r['type'],
        name=r['name'],
        updated_at=r['updated_at'],
        last_message=last_message,
        other_user=other_user,
    )


@router.get('/{chat_id}/messages', response_model=list[MessageResponse])
async def get_chat_messages(
    chat_id: UUID,
    cursor_id: UUID | None = Query(None),
    cursor_created_at: datetime | None = Query(None),
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    query, params = build_get_messages_query(user_id, chat_id, cursor_id, cursor_created_at)
    try:
        rows = await conn.fetch(query, *params)
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch messages. Please try again later.',
        )

    if not rows:
        # either the chat doesn't exist or the user is not a participant, return 404 in both cases
        try:
            participant = await conn.fetchval(
                'SELECT 1 FROM chat_participants WHERE chat_id = $1 AND user_id = $2',
                chat_id,
                user_id,
            )
            if not participant:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')
        except HTTPException:
            raise
        except Exception as _:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to fetch messages. Please try again later.',
            )

    messages = []
    for r in rows:
        reply_to = None
        if r['reply_to_id'] is not None:
            reply_to = ReplyToResponse(
                id=r['reply_to_id'],
                content=r['reply_to_content'],
                sender_id=r['reply_to_sender_id'],
                sender_name=r['reply_to_sender_name'],
                is_deleted=r['reply_to_is_deleted'],
            )
        messages.append(
            MessageResponse(
                id=r['id'],
                chat_id=r['chat_id'],
                sender_id=r['sender_id'],
                sender_name=r['sender_name'],
                sender_avatar_url=r['sender_avatar_url'],
                content=r['content'],
                reply_to=reply_to,
                edited_at=r['edited_at'],
                is_deleted=r['is_deleted'],
                created_at=r['created_at'],
            )
        )

    return messages


@router.post('/{chat_id}/messages', response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    chat_id: UUID,
    body: SendMessageRequest,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    # Note: This endpoint has 3 DB round trips, may need to reduce, add caching, etc. if performance becomes an issue
    try:
        validation = await conn.fetchrow(
            """
            SELECT
                EXISTS (SELECT 1 FROM chat_participants WHERE chat_id = $1 AND user_id = $2) AS is_participant,
                ($3::uuid IS NULL OR EXISTS (SELECT 1 FROM messages WHERE id = $3 AND chat_id = $1)) AS reply_to_valid,
                array_agg(user_id) AS participant_ids
            FROM chat_participants
            WHERE chat_id = $1
            """,
            chat_id,
            user_id,
            body.reply_to_id,
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to send message. Please try again later.',
        )

    if not validation['is_participant']:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')
    if not validation['reply_to_valid']:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid reply_to_id')

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO messages (chat_id, sender_id, content, reply_to_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id, chat_id, sender_id, content, reply_to_id, edited_at, is_deleted, created_at
            """,
            chat_id,
            user_id,
            body.content,
            body.reply_to_id,
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to send message. Please try again later.',
        )

    # fetch sender info and reply_to details in a single query
    try:
        extra = await conn.fetchrow(
            """
            SELECT
                u.name AS sender_name,
                u.avatar_url AS sender_avatar_url,
                r.id AS reply_to_id,
                r.content AS reply_to_content,
                r.sender_id AS reply_to_sender_id,
                r.is_deleted AS reply_to_is_deleted,
                rs.name AS reply_to_sender_name
            FROM users u
            LEFT JOIN messages r ON r.id = $2
            LEFT JOIN users rs ON rs.id = r.sender_id
            WHERE u.id = $1
            """,
            user_id,
            body.reply_to_id,
        )
        if extra is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to send message. Please try again later.',
            )
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to send message. Please try again later.',
        )

    reply_to = None
    if extra['reply_to_id'] is not None:
        reply_to = ReplyToResponse(
            id=extra['reply_to_id'],
            content=extra['reply_to_content'],
            sender_id=extra['reply_to_sender_id'],
            sender_name=extra['reply_to_sender_name'],
            is_deleted=extra['reply_to_is_deleted'],
        )

    msg = MessageResponse(
        id=row['id'],
        chat_id=row['chat_id'],
        sender_id=row['sender_id'],
        sender_name=extra['sender_name'],
        sender_avatar_url=extra['sender_avatar_url'],
        content=row['content'],
        reply_to=reply_to,
        edited_at=row['edited_at'],
        is_deleted=row['is_deleted'],
        created_at=row['created_at'],
    )

    # publish to all participants so they receive the message over WS
    for pid in validation['participant_ids']:
        if str(pid) != user_id:
            await publish(str(pid), {'user_id': str(pid), 'msg': msg.model_dump(mode='json')})

    return msg


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
