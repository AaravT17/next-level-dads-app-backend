import asyncpg
import asyncio
from datetime import datetime
from uuid import UUID
from fastapi import status, HTTPException
from app.config.constants import (
    CHAT_PREVIEWS_PAGE_LIMIT,
    CHAT_MESSAGES_PAGE_LIMIT,
    CHAT_PARTICIPANTS_PAGE_LIMIT,
    CHAT_ADDABLE_PARTICIPANTS_PAGE_LIMIT,
)
from app.config.redis import publish
from app.models.chats import (
    ChatResponse,
    LastMessageResponse,
    OtherUserResponse,
    MessageResponse,
    ReplyToResponse,
    CreateChatRequest,
    SendMessageRequest,
    EditMessageRequest,
    EditMessageResponse,
    ChatParticipantResponse,
    AddParticipantsRequest,
    ChatAddableParticipantResponse,
)


def _build_chat_preview_row(r) -> ChatResponse:
    last_message = None
    if r['last_message_id'] is not None:
        last_message = LastMessageResponse(
            id=r['last_message_id'],
            content='' if r['last_message_is_deleted'] else r['last_message_content'],
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
        last_read_at=r['last_read_at'],
        last_message=last_message,
        other_user=other_user,
    )


_CHAT_PREVIEW_QUERY = """
    SELECT
        c.id,
        c.type,
        c.name,
        c.updated_at,
        cp.last_read_at,
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
    name: str | None = None,
) -> list[ChatResponse]:
    conditions = ['cp.user_id = $1']
    params = [user_id]
    i = 2

    if cursor_updated_at and cursor_id:
        conditions.append(f'(c.updated_at, c.id) < (${i}, ${i + 1})')
        params.extend([cursor_updated_at, cursor_id])
        i += 2

    if name:
        conditions.append(f"(c.type = 'group' AND c.name ILIKE ${i} OR c.type = 'dm' AND ou.name ILIKE ${i})")
        params.append(f'%{name}%')
        i += 1

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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail='You can only add users with whom you are connected'
        )

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
            existing_chat_id = await conn.fetchval(
                """
                SELECT id FROM chats
                WHERE (dm_user_1 = $1 AND dm_user_2 = $2) OR (dm_user_1 = $2 AND dm_user_2 = $1)
                """,
                user_id,
                participant_ids[0],
            )
            return {'id': str(existing_chat_id), 'created': False}
        except Exception as _:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to create chat. Please try again later.',
            )
    else:
        try:
            async with conn.transaction():
                chat_id = await conn.fetchval(
                    "INSERT INTO chats (type, name, created_by) VALUES ('group', $1, $2) RETURNING id",
                    name,
                    user_id,
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

    return {'id': str(chat_id), 'created': True}


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
                content='' if r['reply_to_is_deleted'] else r['reply_to_content'],
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
                content='' if r['is_deleted'] else r['content'],
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
    # TODO: Move sending messages to be over WebSocket instead of REST, more performant
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
            content='' if extra['reply_to_is_deleted'] else extra['reply_to_content'],
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
        _publish_event(
            publish_to=[pid for pid in validation['participant_ids'] if str(pid) != str(user_id)],
            type='messages:new',
            payload=msg.model_dump(mode='json'),
        )
    )

    return msg


async def _publish_event(
    publish_to: list[UUID],
    type: str,
    payload: dict,
) -> None:
    for uid in publish_to:
        try:
            await publish(str(uid), {'user_id': str(uid), 'event_data': {'type': type, 'payload': payload}})
        except Exception as _:
            # add proper logging here
            pass


async def edit_message(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    message_id: UUID,
    body: EditMessageRequest,
) -> EditMessageResponse:
    try:
        result = await conn.fetchrow(
            """
            WITH updated AS (
                UPDATE messages
                SET content = $4, edited_at = NOW()
                WHERE id = $1 AND chat_id = $2 AND sender_id = $3 AND is_deleted = FALSE
                RETURNING id, content, edited_at, chat_id
            )
            SELECT
                updated.id,
                updated.chat_id,
                updated.content,
                updated.edited_at,
                array_agg(cp.user_id) AS participant_ids
            FROM updated
            JOIN chat_participants cp ON cp.chat_id = updated.chat_id
            GROUP BY updated.id, updated.chat_id, updated.content, updated.edited_at
            """,
            message_id,
            chat_id,
            user_id,
            body.new_content,
        )
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Message not found')
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to edit message. Please try again later.',
        )

    asyncio.create_task(
        _publish_event(
            publish_to=[pid for pid in result['participant_ids'] if str(pid) != str(user_id)],
            type='messages:edit',
            payload={
                'id': str(result['id']),
                'chat_id': str(result['chat_id']),
                'content': result['content'],
                'edited_at': result['edited_at'].isoformat(),
                'is_deleted': False,
            },
        )
    )

    return EditMessageResponse(id=result['id'], content=result['content'], edited_at=result['edited_at'])


async def delete_message(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    message_id: UUID,
) -> None:
    try:
        result = await conn.fetchrow(
            """
            WITH updated AS (
                UPDATE messages
                SET is_deleted = TRUE
                WHERE id = $1 AND chat_id = $2 AND sender_id = $3
                RETURNING id, chat_id
            )
            SELECT
                updated.id,
                updated.chat_id,
                array_agg(cp.user_id) AS participant_ids
            FROM updated
            JOIN chat_participants cp ON cp.chat_id = updated.chat_id
            GROUP BY updated.id, updated.chat_id
            """,
            message_id,
            chat_id,
            user_id,
        )
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Message not found')
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to delete message. Please try again later.',
        )

    asyncio.create_task(
        _publish_event(
            publish_to=[pid for pid in result['participant_ids'] if str(pid) != str(user_id)],
            type='messages:delete',
            payload={
                'id': str(result['id']),
                'chat_id': str(result['chat_id']),
                'content': '',
                'is_deleted': True,
                'edited_at': None,
            },
        )
    )


async def get_participants(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    cursor_id: UUID | None,
    cursor_joined_at: datetime | None,
) -> list[ChatParticipantResponse]:
    try:
        validation = await conn.fetchval(
            'SELECT 1 FROM chat_participants WHERE chat_id = $1 AND user_id = $2',
            chat_id,
            user_id,
        )
        if not validation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch participants. Please try again later.',
        )

    conditions = ['cp.chat_id = $1']
    params = [chat_id]
    i = 2

    if cursor_joined_at and cursor_id:
        conditions.append(f'(cp.joined_at, cp.user_id) < (${i}, ${i + 1})')
        params.extend([cursor_joined_at, cursor_id])
        i += 2

    where_clause = ' AND '.join(conditions)
    params.append(CHAT_PARTICIPANTS_PAGE_LIMIT)

    try:
        rows = await conn.fetch(
            f"""
            SELECT
                u.id,
                u.name,
                u.avatar_url,
                cp.joined_at,
                (CASE WHEN cp.is_admin THEN 'admin' ELSE 'member' END) AS role
            FROM chat_participants cp
            JOIN users u ON u.id = cp.user_id
            WHERE {where_clause}
            ORDER BY cp.joined_at DESC, cp.user_id DESC
            LIMIT ${i}
            """,
            *params,
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch participants. Please try again later.',
        )

    return [ChatParticipantResponse(**dict(r)) for r in rows]


async def add_participants(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    body: AddParticipantsRequest,
) -> list[ChatParticipantResponse]:
    new_participant_ids = body.new_participant_ids
    try:
        # verify that:
        #   - the chat exists and the current user is a participant
        #   - the chat is a group chat
        #   - the current user is an admin
        #   - the new participants are connected with the current user
        validation = await conn.fetchrow(
            """
            SELECT
                cp.is_admin,
                c.type,
                (SELECT array_agg(CASE WHEN requesting_id = $2 THEN requested_id ELSE requesting_id END)
                FROM connections
                WHERE (requesting_id = $2 OR requested_id = $2) AND status = 'accepted') AS connections
            FROM chat_participants cp JOIN chats c ON c.id = cp.chat_id
            WHERE cp.chat_id = $1 AND cp.user_id = $2
            """,
            chat_id,
            user_id,
        )
        if not validation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')
        if validation['type'] != 'group':
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot add participants to a DM chat')
        if not validation['is_admin']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='You do not have permission to add participants to this chat',
            )

        if validation['connections'] is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail='You can only add users with whom you are connected'
            )

        connected_ids = set(validation['connections'])
        if any(pid not in connected_ids for pid in new_participant_ids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail='You can only add users with whom you are connected'
            )

        # add new participants and return their info in one round trip
        res = await conn.fetch(
            """
            WITH inserted AS (
                INSERT INTO chat_participants (chat_id, user_id)
                SELECT $1, unnest($2::uuid[])
                ON CONFLICT DO NOTHING
                RETURNING user_id, joined_at, is_admin
            )
            SELECT
                u.id,
                u.name,
                u.avatar_url,
                i.joined_at,
                (CASE WHEN i.is_admin THEN 'admin' ELSE 'member' END) AS role
            FROM inserted i JOIN users u ON u.id = i.user_id
            ORDER BY i.joined_at DESC, i.user_id DESC
            """,
            chat_id,
            new_participant_ids,
        )
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to add participant. Please try again later.',
        )

    return [ChatParticipantResponse(**dict(r)) for r in res]


async def remove_participant(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    participant_id: UUID,
) -> None:
    # prevent users from removing themselves, they should use the leave chat endpoint instead
    if str(user_id) == str(participant_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='You cannot remove yourself from the chat. Please leave the chat instead.',
        )

    try:
        # verify that the current user has permission to remove the participant:
        #   - the current user must be an admin
        #   - the user they are trying to remove must not be the owner
        validation = await conn.fetchrow(
            """
            SELECT
                is_admin,
                (EXISTS (SELECT 1 FROM chats WHERE id = $1 AND created_by = $3)) AS is_owner
            FROM chat_participants
            WHERE chat_id = $1 AND user_id = $2
            """,
            chat_id,
            user_id,
            participant_id,
        )
        if not validation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')
        if not validation['is_admin'] or validation['is_owner']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail='You cannot remove this participant from the chat'
            )
        await conn.execute(
            'DELETE FROM chat_participants WHERE chat_id = $1 AND user_id = $2',
            chat_id,
            participant_id,
        )
        return
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to remove participant. Please try again later.',
        )


async def leave_chat(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
):
    # TODO: Cannot leave a DM chat, also, on unconnect, delete the DM chat if it exists
    try:
        await conn.execute(
            """
            WITH clear_owner AS (
                UPDATE chats
                SET created_by = NULL
                WHERE id = $1 AND created_by = $2
            ),
            remove_participant AS (
                DELETE FROM chat_participants
                WHERE chat_id = $1 AND user_id = $2
                RETURNING chat_id
            ),
            remaining_participants AS (
                SELECT COUNT(*) AS count
                FROM chat_participants
                WHERE chat_id = $1 AND user_id != $2
            )
            DELETE FROM chats
            WHERE id = $1 AND (SELECT count FROM remaining_participants) = 0
            """,
            chat_id,
            user_id,
        )
        return
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to leave chat. Please try again later.',
        )


async def promote_participant(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    participant_id: UUID,
):
    # self-promotion check not necessary - the user can only promote somebody if they are an admin, and if they are
    # already an admin, then promoting themselves would be a no-op
    try:
        # verify that the current user has permission to promote the participant i.e. they must be an admin
        validation = await conn.fetchrow(
            """
            SELECT is_admin
            FROM chat_participants
            WHERE chat_id = $1 AND user_id = $2
            """,
            chat_id,
            user_id,
        )
        if not validation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')
        if not validation['is_admin']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail='You cannot make this participant an admin'
            )
        await conn.execute(
            """
            UPDATE chat_participants
            SET is_admin = TRUE
            WHERE chat_id = $1 AND user_id = $2
            """,
            chat_id,
            participant_id,
        )
        return
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to make participant an admin. Please try again later.',
        )


async def demote_participant(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    participant_id: UUID,
):
    # prevent users from demoting themselves
    if str(user_id) == str(participant_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='You cannot demote yourself.')

    try:
        # verify that the current user has permission to demote the participant:
        #   - they must be an admin
        #   - the participant they are trying to demote must not be the owner
        validation = await conn.fetchrow(
            """
            SELECT
                is_admin,
                (EXISTS (SELECT 1 FROM chats WHERE id = $1 AND created_by = $3)) AS is_owner
            FROM chat_participants
            WHERE chat_id = $1 AND user_id = $2
            """,
            chat_id,
            user_id,
            participant_id,
        )
        if not validation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')
        if not validation['is_admin'] or validation['is_owner']:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You cannot demote this participant.')
        await conn.execute(
            """
            UPDATE chat_participants
            SET is_admin = FALSE
            WHERE chat_id = $1 AND user_id = $2
            """,
            chat_id,
            participant_id,
        )
        return
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to demote participant. Please try again later.',
        )


async def get_addable_participants(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    user_name: str | None,
    cursor_id: UUID | None,
    cursor_name: str | None,
) -> list[ChatAddableParticipantResponse]:
    try:
        # verify that the chat exists, is a group chat, and the user is a participant
        validation = await conn.fetchrow(
            """
            SELECT c.type
            FROM chat_participants cp JOIN chats c ON c.id = cp.chat_id
            WHERE cp.chat_id = $1 AND cp.user_id = $2
            """,
            chat_id,
            user_id,
        )
        if not validation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')
        if validation['type'] != 'group':
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot add participants to a DM chat')

        # fetch users that the current user is connected with but are not already participants in the chat
        conditions = [
            "(c.requesting_id = $2 OR c.requested_id = $2) AND c.status = 'accepted'",
            'u.id NOT IN (SELECT user_id FROM chat_participants WHERE chat_id = $1)',
        ]
        params = [chat_id, user_id]
        i = 3

        if user_name:
            conditions.append(f"u.name ILIKE ${i} || '%'")
            params.append(user_name)
            i += 1

        if cursor_name and cursor_id:
            conditions.append(f'(u.name, u.id) > (${i}, ${i + 1})')
            params.extend([cursor_name, cursor_id])
            i += 2

        where_clause = ' AND '.join(conditions)

        query = f"""
            SELECT u.id, u.name, u.avatar_url
            FROM connections c 
            JOIN users u ON u.id = (CASE WHEN c.requesting_id = $2 THEN c.requested_id ELSE c.requesting_id END)
            WHERE {where_clause}
            ORDER BY u.name ASC, u.id ASC
            LIMIT ${i}
        """
        params.append(CHAT_ADDABLE_PARTICIPANTS_PAGE_LIMIT)
        rows = await conn.fetch(query, *params)
        return [ChatAddableParticipantResponse(**dict(r)) for r in rows]
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch addable participants. Please try again later.',
        )


async def mark_chat_read(conn: asyncpg.Connection, user_id: str, chat_id: str) -> datetime | None:
    return await conn.fetchval(
        """
        UPDATE chat_participants
        SET last_read_at = NOW()
        WHERE user_id = $1 AND chat_id = $2
        RETURNING last_read_at
        """,
        user_id,
        chat_id,
    )
