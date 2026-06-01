from datetime import datetime
from uuid import UUID
from app.config.constants import CHAT_PREVIEWS_PAGE_LIMIT, CHAT_MESSAGES_PAGE_LIMIT


def build_get_chat_previews_query(
    user_id: UUID,
    cursor_id: UUID | None = None,
    cursor_updated_at: datetime | None = None,
) -> tuple[str, list]:
    conditions = ['cp.user_id = $1']
    params = [user_id]
    i = 2

    if cursor_updated_at and cursor_id:
        conditions.append(f'(c.updated_at, c.id) < (${i}, ${i + 1})')
        params.extend([cursor_updated_at, cursor_id])
        i += 2

    where_clause = ' AND '.join(conditions)
    query = f"""
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
        WHERE {where_clause}
        ORDER BY c.updated_at DESC, c.id DESC
        LIMIT ${i}
    """
    params.append(CHAT_PREVIEWS_PAGE_LIMIT)

    return query, params


def build_get_chat_preview_query(user_id: UUID, chat_id: UUID) -> tuple[str, list]:
    query = """
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
        WHERE cp.user_id = $1 AND c.id = $2
    """
    return query, [user_id, chat_id]


def build_get_messages_query(
    user_id: UUID,
    chat_id: UUID,
    cursor_id: UUID | None = None,
    cursor_created_at: datetime | None = None,
) -> tuple[str, list]:
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

    return query, params
