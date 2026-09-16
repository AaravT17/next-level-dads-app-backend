import asyncpg
import asyncio
import logging
from datetime import datetime
from uuid import UUID
from fastapi import status, HTTPException
from app.common.config.constants import (
    CHAT_PREVIEWS_PAGE_LIMIT,
    CHAT_MESSAGES_PAGE_LIMIT,
    CHAT_PARTICIPANTS_PAGE_LIMIT,
    CHAT_ADDABLE_PARTICIPANTS_PAGE_LIMIT,
)
from app.common.utils.tasks import spawn, safe_publish
import app.modules.notifications.service as notifications_service
from app.modules.chats.models import (
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
    SharedCommunityResponse,
    ChatMembershipResponse,
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


def _build_shared_community(r) -> SharedCommunityResponse | None:
    """The community card on an invite message, or None when there isn't one.

    A deleted message keeps its row but shows as "Message deleted", so the card
    is withheld too — otherwise deleting an invite would leave the link standing.
    """
    if r['shared_community_id'] is None or r['is_deleted']:
        return None
    return SharedCommunityResponse(
        id=r['shared_community_id'],
        name=r['shared_community_name'],
        description=r['shared_community_description'],
        image_url=r['shared_community_image_url'],
        member_count=r['shared_community_member_count'] or 0,
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


logger = logging.getLogger(__name__)



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
    pool: asyncpg.Pool,
) -> dict:
    chat_id: UUID | None = None
    # participant IDs are deduplicated by the validation layer, need not worry about that here
    try:
        async with conn.transaction():
            # Validate participant IDs: must be connected with current user (implicitly excludes self)
            # Add a read-lock (FOR SHARE) on the connection rows to prevent them from being deleted while we are
            # creating the chat. This will prevent a DM chat from persisting after the connection is removed.
            connections = await conn.fetch(
                """
                SELECT (CASE WHEN requesting_id = $1 THEN requested_id ELSE requesting_id END) AS user_id
                FROM connections
                WHERE (requesting_id = $1 OR requested_id = $1) AND status = 'accepted'
                FOR SHARE
                """,
                user_id,
            )
            connected_ids = {r['user_id'] for r in connections}
            if any(pid not in connected_ids for pid in body.participant_ids):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail='You can only add users to a chat if you are connected with them.',
                )

            if len(body.participant_ids) == 1:
                is_group = False
                row = await conn.fetchrow(
                    """
                    INSERT INTO chats (type, dm_user_1, dm_user_2) VALUES ('dm', $1, $2)
                    RETURNING id, (SELECT name FROM users WHERE id = $1) AS creator_name
                    """,
                    user_id,
                    body.participant_ids[0],
                )  # can raise a UniqueViolationError if a DM chat between the two users already exists
                chat_id = row['id']
                creator_name = row['creator_name']
                await conn.executemany(
                    'INSERT INTO chat_participants (chat_id, user_id) VALUES ($1, $2)',
                    [(chat_id, user_id), (chat_id, body.participant_ids[0])],
                )
            else:
                is_group = True
                row = await conn.fetchrow(
                    """
                    INSERT INTO chats (type, name, created_by) VALUES ('group', $1, $2)
                    RETURNING id, (SELECT name FROM users WHERE id = $2) AS creator_name
                    """,
                    body.name,
                    user_id,
                )
                chat_id = row['id']
                creator_name = row['creator_name']
                await conn.executemany(
                    'INSERT INTO chat_participants (chat_id, user_id, is_admin) VALUES ($1, $2, $3)',
                    [(chat_id, pid, False) for pid in body.participant_ids] + [(chat_id, user_id, True)],
                )
    except HTTPException:
        raise
    except asyncpg.UniqueViolationError:
        # a DM chat between the two users already exists, return the existing chat ID
        try:
            existing_chat_id = await conn.fetchval(
                """
                SELECT id FROM chats
                WHERE (dm_user_1 = $1 AND dm_user_2 = $2) OR (dm_user_1 = $2 AND dm_user_2 = $1)
                """,
                user_id,
                body.participant_ids[0],
            )
            return {'id': str(existing_chat_id), 'created': False}
        except Exception:
            logger.exception('Failed to fetch existing chat ID after unique violation')
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to create chat. Please try again later.',
            )
    except Exception:
        logger.exception('Failed to create chat')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to create chat. Please try again later.',
        )

    # publish chats:added and create notification rows (for group chats only)
    payload = {
        'chat_id': str(chat_id),
        'chat_name': body.name if is_group else None,
        'chat_type': 'group' if is_group else 'dm',
        'chat_avatar_url': None,
        'added_by': str(user_id),
        'added_by_name': creator_name,
    }
    all_participant_ids = [user_id] + body.participant_ids
    spawn(_notify_chat_added(pool, all_participant_ids, user_id, payload, is_group))

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
            r.is_deleted AS reply_to_is_deleted,
            m.shared_community_id,
            sc.name AS shared_community_name,
            sc.description AS shared_community_description,
            sc.image_url AS shared_community_image_url,
            (SELECT COUNT(*) FROM community_members cm WHERE cm.community_id = sc.id)
                AS shared_community_member_count
        FROM messages m
        LEFT JOIN users s ON s.id = m.sender_id
        LEFT JOIN messages r ON r.id = m.reply_to_id
        LEFT JOIN users rs ON rs.id = r.sender_id
        LEFT JOIN communities sc ON sc.id = m.shared_community_id
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
                shared_community=_build_shared_community(r),
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
                ($3::uuid IS NULL OR EXISTS (SELECT 1 FROM messages WHERE id = $3 AND chat_id = $1)) AS reply_to_valid
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
            WITH inserted AS (
                INSERT INTO messages (chat_id, sender_id, content, reply_to_id)
                VALUES ($1, $2, $3, $4)
                RETURNING id, chat_id, sender_id, content, reply_to_id, edited_at, is_deleted, created_at
            )
            SELECT
                i.id, 
                i.chat_id, 
                i.sender_id, 
                i.content, 
                i.edited_at, 
                i.is_deleted, 
                i.created_at,
                u.name AS sender_name,
                u.avatar_url AS sender_avatar_url,
                c.name AS chat_name,
                c.type AS chat_type,
                r.id AS reply_to_id,
                r.content AS reply_to_content,
                r.sender_id AS reply_to_sender_id,
                r.is_deleted AS reply_to_is_deleted,
                rs.name AS reply_to_sender_name
            FROM inserted i
            JOIN users u ON u.id = i.sender_id
            JOIN chats c ON c.id = i.chat_id
            LEFT JOIN messages r ON r.id = i.reply_to_id
            LEFT JOIN users rs ON rs.id = r.sender_id
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

    reply_to = None
    if row['reply_to_id'] is not None:
        reply_to = ReplyToResponse(
            id=row['reply_to_id'],
            content='' if row['reply_to_is_deleted'] else row['reply_to_content'],
            sender_id=row['reply_to_sender_id'],
            sender_name=row['reply_to_sender_name'],
            is_deleted=row['reply_to_is_deleted'],
        )

    msg = MessageResponse(
        id=row['id'],
        chat_id=row['chat_id'],
        sender_id=row['sender_id'],
        sender_name=row['sender_name'],
        sender_avatar_url=row['sender_avatar_url'],
        content=row['content'],
        reply_to=reply_to,
        edited_at=row['edited_at'],
        is_deleted=row['is_deleted'],
        created_at=row['created_at'],
    )

    # Published on the chat's own channel, which reaches the sender's other
    # sockets too -- the per-user scheme had to exclude the sender and left them
    # unsynced across devices.
    msg_payload = msg.model_dump(mode='json')
    msg_payload['chat_name'] = row['chat_name']
    msg_payload['chat_type'] = row['chat_type']
    msg_payload['chat_avatar_url'] = None  # no group avatars yet
    spawn(safe_publish(f'chat:{chat_id}', {'type': 'messages:new', 'payload': msg_payload}))

    return msg


async def _notify_chat_added(
    pool: asyncpg.Pool,
    participant_ids: list[UUID],
    added_by: UUID,
    payload: dict,
    is_group: bool,
) -> None:
    """Create chat_added notification rows (for group chats only) and publish the WS event. Best-effort."""
    if is_group:
        notifications = [(uid, 'chat_added', payload) for uid in participant_ids if uid != added_by]
        async with pool.acquire() as conn:
            await notifications_service.create_notifications_bulk(conn, notifications)
    await asyncio.gather(
        *[safe_publish(f'user:{uid}', {'type': 'chats:added', 'payload': payload}) for uid in participant_ids]
    )


async def _publish_community_invite(
    sender_id: UUID,
    recipient_id: UUID,
    chat_id: UUID,
    chat_created: bool,
    sender_name: str | None,
    msg_payload: dict,
) -> None:
    """Publish WS events for a community invite DM.

    When the DM was just created, publishes chats:added first so the connection
    manager subscribes both users to the chat channel before the messages:new
    event arrives. Running both steps in a single background task guarantees
    ordering — separate spawn calls do not.
    """
    if chat_created:
        added_payload = {
            'chat_id': str(chat_id),
            'chat_name': None,
            'chat_type': 'dm',
            'chat_avatar_url': None,
            'added_by': str(sender_id),
            'added_by_name': sender_name,
        }
        added_event = {'type': 'chats:added', 'payload': added_payload}
        await asyncio.gather(
            safe_publish(f'user:{recipient_id}', added_event),
            safe_publish(f'user:{sender_id}', added_event),
        )
    await safe_publish(f'chat:{chat_id}', {'type': 'messages:new', 'payload': msg_payload})


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
            UPDATE messages
            SET content = $4, edited_at = NOW()
            WHERE id = $1 AND chat_id = $2 AND sender_id = $3 AND is_deleted = FALSE
            RETURNING id, chat_id, content, edited_at
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

    spawn(
        safe_publish(
            f'chat:{chat_id}',
            {
                'type': 'messages:edit',
                'payload': {
                    'id': str(result['id']),
                    'chat_id': str(result['chat_id']),
                    'content': result['content'],
                    'edited_at': result['edited_at'].isoformat(),
                    'is_deleted': False,
                },
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
            UPDATE messages
            SET is_deleted = TRUE
            WHERE id = $1 AND chat_id = $2 AND sender_id = $3
            RETURNING id, chat_id
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

    spawn(
        safe_publish(
            f'chat:{chat_id}',
            {
                'type': 'messages:delete',
                'payload': {
                    'id': str(result['id']),
                    'chat_id': str(result['chat_id']),
                    'content': '',
                    'is_deleted': True,
                    'edited_at': None,
                },
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
    pool: asyncpg.Pool,
) -> list[ChatParticipantResponse]:
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
                c.name AS chat_name,
                (SELECT name FROM users WHERE id = $2) AS adder_name,
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
                status_code=status.HTTP_403_FORBIDDEN,
                detail='You can only add users to a chat if you are connected with them.',
            )

        connected_ids = set(validation['connections'])
        if any(pid not in connected_ids for pid in body.new_participant_ids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='You can only add users to a chat if you are connected with them.',
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
            body.new_participant_ids,
        )
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to add participant. Please try again later.',
        )

    # notify added participants and publish chats:added (best-effort, background)
    added_user_ids = [r['id'] for r in res]
    if added_user_ids:
        payload = {
            'chat_id': str(chat_id),
            'chat_name': validation['chat_name'],
            'chat_type': 'group',
            'chat_avatar_url': None,
            'added_by': str(user_id),
            'added_by_name': validation['adder_name'],
        }
        spawn(_notify_chat_added(pool, added_user_ids, user_id, payload, is_group=True))

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
            detail='You cannot remove yourself from the chat.',
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found.')
        if not validation['is_admin'] or validation['is_owner']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail='You cannot remove this participant from the chat.'
            )
        await conn.execute(
            'DELETE FROM chat_participants WHERE chat_id = $1 AND user_id = $2',
            chat_id,
            participant_id,
        )
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to remove participant. Please try again later.',
        )

    spawn(safe_publish(f'user:{participant_id}', {'type': 'chats:removed', 'payload': {'chat_id': str(chat_id)}}))
    return


async def leave_chat(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
):
    try:
        await conn.execute(
            """
            WITH clear_owner AS (
                UPDATE chats
                SET created_by = NULL
                WHERE id = $1 AND created_by = $2 AND type = 'group'
            ),
            remove_participant AS (
                DELETE FROM chat_participants
                WHERE chat_id = $1 AND user_id = $2
                AND (SELECT type FROM chats WHERE id = $1) = 'group'
                RETURNING chat_id
            ),
            remaining_participants AS (
                SELECT COUNT(*) AS count
                FROM chat_participants
                WHERE chat_id = $1 AND user_id != $2
            )
            DELETE FROM chats
            WHERE id = $1 AND type = 'group' AND (SELECT count FROM remaining_participants) = 0
            """,
            chat_id,
            user_id,
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to leave chat. Please try again later.',
        )

    spawn(safe_publish(f'user:{user_id}', {'type': 'chats:removed', 'payload': {'chat_id': str(chat_id)}}))
    return


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
        result = await conn.execute(
            """
            UPDATE chat_participants
            SET is_admin = TRUE
            WHERE chat_id = $1 AND user_id = $2
            """,
            chat_id,
            participant_id,
        )
        # A participant_id that is not in this chat matches no row. Without this
        # the caller gets 204 and believes someone was promoted who was not.
        if result.split()[-1] == '0':
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Participant not found in this chat.',
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
        result = await conn.execute(
            """
            UPDATE chat_participants
            SET is_admin = FALSE
            WHERE chat_id = $1 AND user_id = $2
            """,
            chat_id,
            participant_id,
        )
        # Same reasoning as promote_participant: a participant_id that is not in
        # this chat matches no row, and a bare 204 would tell the caller someone
        # was demoted who was not.
        if result.split()[-1] == '0':
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Participant not found in this chat.',
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


async def update_chat_name(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    name: str,
) -> None:
    try:
        validation = await conn.fetchrow(
            """
            SELECT c.type, cp.is_admin
            FROM chat_participants cp
            JOIN chats c ON c.id = cp.chat_id
            WHERE cp.chat_id = $1 AND cp.user_id = $2
            """,
            chat_id,
            user_id,
        )
        if not validation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat not found')
        if validation['type'] != 'group':
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Only group chats can have a name')
        if not validation['is_admin']:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only admins can update the chat name')

        await conn.execute(
            """
            UPDATE chats
            SET name = $1
            WHERE id = $2
            """,
            name,
            chat_id,
        )
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to update chat name. Please try again later.',
        )


async def mark_chat_read(conn: asyncpg.Connection, user_id: str, chat_id: str) -> datetime | None:
    return await conn.fetchval(
        """
        UPDATE chat_participants
        SET last_read_at = GREATEST(COALESCE(last_read_at, NOW()), NOW())
        WHERE user_id = $1 AND chat_id = $2
        RETURNING last_read_at
        """,
        user_id,
        chat_id,
    )


async def _get_or_create_dm(
    conn: asyncpg.Connection,
    user_id: UUID,
    other_user_id: UUID,
) -> tuple[UUID, bool]:
    """The DM between two users, created on first use, and whether this call created it.

    Runs inside a savepoint so the losing side of a concurrent create can fall
    back to the existing row without aborting the caller's transaction.
    """
    chat_id = await conn.fetchval(
        """
        SELECT id FROM chats
        WHERE type = 'dm'
          AND LEAST(dm_user_1, dm_user_2) = LEAST($1::uuid, $2::uuid)
          AND GREATEST(dm_user_1, dm_user_2) = GREATEST($1::uuid, $2::uuid)
        """,
        user_id,
        other_user_id,
    )
    if chat_id is not None:
        return chat_id, False

    try:
        async with conn.transaction():
            chat_id = await conn.fetchval(
                "INSERT INTO chats (type, dm_user_1, dm_user_2) VALUES ('dm', $1, $2) RETURNING id",
                user_id,
                other_user_id,
            )
            await conn.executemany(
                'INSERT INTO chat_participants (chat_id, user_id) VALUES ($1, $2)',
                [(chat_id, user_id), (chat_id, other_user_id)],
            )
        return chat_id, True
    except asyncpg.UniqueViolationError:
        existing_chat_id = await conn.fetchval(
            """
            SELECT id FROM chats
            WHERE type = 'dm'
              AND LEAST(dm_user_1, dm_user_2) = LEAST($1::uuid, $2::uuid)
              AND GREATEST(dm_user_1, dm_user_2) = GREATEST($1::uuid, $2::uuid)
            """,
            user_id,
            other_user_id,
        )
        return existing_chat_id, False


async def send_community_invites(
    conn: asyncpg.Connection,
    sender_id: UUID,
    recipient_ids: list[UUID],
    community: SharedCommunityResponse,
    content: str,
) -> list[UUID]:
    """Drop one invite message into the sender's DM with each recipient.

    All of it in one transaction: an invite that reaches four of five friends is
    worse than one that fails outright, because the sender cannot tell which.
    Callers are responsible for validating the recipients and the community.
    """
    # Read before writing: the publish below needs it, and a failure here should
    # cost nothing. After the commit there is no honest way to fail the request.
    try:
        sender = await conn.fetchrow('SELECT name, avatar_url FROM users WHERE id = $1', sender_id)
        if not sender:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to send invites. Please try again later.',
            )
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to send invites. Please try again later.',
        )

    sent: list[tuple[UUID, UUID, UUID, datetime, bool]] = []
    try:
        async with conn.transaction():
            for recipient_id in recipient_ids:
                chat_id, chat_created = await _get_or_create_dm(conn, sender_id, recipient_id)
                row = await conn.fetchrow(
                    """
                    INSERT INTO messages (chat_id, sender_id, content, shared_community_id)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id, created_at
                    """,
                    chat_id,
                    sender_id,
                    content,
                    community.id,
                )
                sent.append((recipient_id, chat_id, row['id'], row['created_at'], chat_created))
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to send invites. Please try again later.',
        )

    # Published only after the transaction commits, so a recipient that reacts by
    # fetching the chat cannot beat the rows it is fetching.
    for recipient_id, chat_id, message_id, created_at, chat_created in sent:
        msg = MessageResponse(
            id=message_id,
            chat_id=chat_id,
            sender_id=sender_id,
            sender_name=sender['name'],
            sender_avatar_url=sender['avatar_url'],
            content=content,
            shared_community=community,
            is_deleted=False,
            created_at=created_at,
        )
        msg_payload = msg.model_dump(mode='json')
        msg_payload['chat_name'] = None
        msg_payload['chat_type'] = 'dm'
        msg_payload['chat_avatar_url'] = None
        spawn(
            _publish_community_invite(
                sender_id,
                recipient_id,
                chat_id,
                chat_created,
                sender['name'],
                msg_payload,
            )
        )

    return [chat_id for _, chat_id, _, _, _ in sent]


async def get_user_chat_memberships(conn: asyncpg.Connection, user_id: str) -> list[ChatMembershipResponse]:
    """Return chat_id, last_read_at, updated_at for all chats the user is a participant in."""
    try:
        rows = await conn.fetch(
            """
            SELECT c.id AS chat_id, cp.last_read_at, c.updated_at
            FROM chat_participants cp
            JOIN chats c ON c.id = cp.chat_id
            WHERE cp.user_id = $1
            """,
            user_id,
        )
        return [ChatMembershipResponse(**dict(r)) for r in rows]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch chat memberships. Please try again later.',
        )


async def get_user_chat_ids(conn: asyncpg.Connection, user_id: str) -> set[str]:
    """Return the IDs of all chats that the user is a participant in."""
    rows = await conn.fetch(
        """
        SELECT chat_id
        FROM chat_participants
        WHERE user_id = $1
        """,
        user_id,
    )
    return {str(r['chat_id']) for r in rows}
