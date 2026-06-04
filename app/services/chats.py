import asyncpg
from datetime import datetime
from uuid import UUID
from fastapi import status, HTTPException
from app.config.constants import CHAT_PREVIEWS_PAGE_LIMIT, CHAT_MESSAGES_PAGE_LIMIT
from app.config.redis import publish
from app.models.chats import (
    ChatResponse,
    LastMessageResponse,
    OtherUserResponse,
    MessageResponse,
    ReplyToResponse,
    CreateChatRequest,
    SendMessageRequest,
)
import asyncio


def _build_chat_preview_row(r) -> ChatResponse:
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


_CHAT_PREVIEW_QUERY = """
    SELECT
        c.id,
        c.type,
        c.name,
        c.updated_at,
        lm.id AS last_message_id,
        lm.content AS last_message_content,
        lm.sender_id AS last_message_sender_id,
        lm.sender_name AS last_message_sender_name,
        lm.created_at AS last_message_created_at,
        lm.is_deleted AS last_message_is_deleted,
        ou.id AS other_user_id,
        ou.name AS other_user_name,
        ou.avatar_url AS other_user_avatar_url
    FROM chat_participants cp
    JOIN chats c ON c.id = cp.chat_id
    LEFT JOIN last_messages lm ON lm.chat_id = c.id
    LEFT JOIN users ou ON c.type = 'dm'
        AND ou.id = CASE
            WHEN c.dm_user_1 = $1 THEN c.dm_user_2
            ELSE c.dm_user_1
        END
"""


async def get_chat_previews(
    conn: asyncpg.Connection,
    user_id: UUID,
    cursor_id: UUID | None,
    cursor_updated_at: datetime | None,
) -> list[ChatResponse]:
    conditions = ['cp.user_id = $1']
    params = [user_id]
    i = 2

    if cursor_updated_at and cursor_id:
        conditions.append(f'(c.updated_at, c.id) < (${i}, ${i + 1})')
        params.extend([cursor_updated_at, cursor_id])
        i += 2

    where_clause = ' AND '.join(conditions)
    query = f'{_CHAT_PREVIEW_QUERY} WHERE {where_clause} ORDER BY c.updated_at DESC, c.id DESC LIMIT ${i}'
    params.append(CHAT_PREVIEWS_PAGE_LIMIT)

    try:
        rows = await conn.fetch(query, *params)
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch chats. Please try again later.',
        )

    return [_build_chat_preview_row(r) for r in rows]


async def get_chat_preview(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
) -> ChatResponse:
    query = f'{_CHAT_PREVIEW_QUERY} WHERE cp.user_id = $1 AND c.id = $2'

    try:
        r = await conn.fetchrow(query, user_id, chat_id)
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch chat. Please try again later.',
        )

    if r is None:
        # either the chat doesn't exist or the user is not a participant — don't reveal which
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')

    return _build_chat_preview_row(r)


async def create_chat(
    conn: asyncpg.Connection,
    user_id: UUID,
    body: CreateChatRequest,
) -> dict:
    name, participant_ids = body.name, body.participant_ids

    # validate participant IDs: must be connected with current user (implicitly checks existence and excludes self)
    try:
        connections = await conn.fetch(
            """
            SELECT (CASE WHEN requesting_id = $1 THEN requested_id ELSE requesting_id END) AS user_id
            FROM connections
            WHERE (requesting_id = $1 OR requested_id = $1) AND status = 'accepted'
            """,
            user_id,
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to create chat. Please try again later.',
        )

    connected_ids = set(r['user_id'] for r in connections)
    if any(pid not in connected_ids for pid in participant_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid participant IDs')

    if len(participant_ids) == 1:
        try:
            async with conn.transaction():
                chat_id = await conn.fetchval(
                    "INSERT INTO chats (type, dm_user_1, dm_user_2) VALUES ('dm', $1, $2) RETURNING id",
                    user_id,
                    participant_ids[0],
                )
                await conn.executemany(
                    'INSERT INTO chat_participants (chat_id, user_id) VALUES ($1, $2)',
                    [(chat_id, user_id), (chat_id, participant_ids[0])],
                )
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='A DM chat with this user already exists')
        except Exception as _:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to create chat. Please try again later.',
            )
    else:
        try:
            async with conn.transaction():
                chat_id = await conn.fetchval(
                    "INSERT INTO chats (type, name) VALUES ('group', $1) RETURNING id",
                    name,
                )
                await conn.executemany(
                    'INSERT INTO chat_participants (chat_id, user_id, is_admin) VALUES ($1, $2, $3)',
                    [(chat_id, pid, False) for pid in participant_ids] + [(chat_id, user_id, True)],
                )
        except Exception as _:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to create chat. Please try again later.',
            )

    return {'id': str(chat_id)}


async def get_messages(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    cursor_id: UUID | None,
    cursor_created_at: datetime | None,
) -> list[MessageResponse]:
    conditions = [
        'EXISTS (SELECT 1 FROM chat_participants cp WHERE cp.chat_id = $1 AND cp.user_id = $2)',
        'm.chat_id = $1',
    ]
    params = [chat_id, user_id]
    i = 3

    if cursor_created_at and cursor_id:
        conditions.append(f'(m.created_at, m.id) < (${i}, ${i + 1})')
        params.extend([cursor_created_at, cursor_id])
        i += 2

    where_clause = ' AND '.join(conditions)
    query = f"""
        SELECT
            m.id,
            m.chat_id,
            m.sender_id,
            s.name AS sender_name,
            s.avatar_url AS sender_avatar_url,
            m.content,
            m.edited_at,
            m.is_deleted,
            m.created_at,
            m.reply_to_id,
            r.content AS reply_to_content,
            r.sender_id AS reply_to_sender_id,
            rs.name AS reply_to_sender_name,
            r.is_deleted AS reply_to_is_deleted
        FROM messages m
        LEFT JOIN users s ON s.id = m.sender_id
        LEFT JOIN messages r ON r.id = m.reply_to_id
        LEFT JOIN users rs ON rs.id = r.sender_id
        WHERE {where_clause}
        ORDER BY m.created_at DESC, m.id DESC
        LIMIT ${i}
    """
    params.append(CHAT_MESSAGES_PAGE_LIMIT)

    try:
        rows = await conn.fetch(query, *params)
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch messages. Please try again later.',
        )

    if not rows:
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


async def send_message(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    body: SendMessageRequest,
) -> MessageResponse:
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

    # publish to all participants except the sender, fire off as background task, don't delay response
    asyncio.create_task(
        _publish_message(
            publish_to=[pid for pid in validation['participant_ids'] if str(pid) != str(user_id)],
            msg=msg,
        )
    )

    return msg


async def _publish_message(
    publish_to: list[UUID],
    msg: MessageResponse,
):
    for uid in publish_to:
        try:
            await publish(str(uid), {'user_id': str(uid), 'msg': msg.model_dump(mode='json')})
        except Exception as _:
            # add proper logging here
            pass
