from datetime import datetime
from typing import Literal
from fastapi import HTTPException, status
from uuid import UUID
import asyncpg

from app.config.constants import CONVERSATIONS_PAGE_LIMIT, MESSAGES_PAGE_LIMIT, REPLIES_PAGE_LIMIT
from app.models.communities import (
    AuthorInfo,
    ConversationResponse,
    MessageResponse,
    ParticipantResponse,
    ReplyResponse,
)

REMOVED_CONVERSATION_TITLE = "Removed post"
REMOVED_BY_ORIGINAL_POSTER = "Removed by original poster."
REMOVED_BY_MODERATOR = "Removed by moderator."

_CONVERSATION_COLS = """
    c.id,
    c.community_id,
    c.title,
    c.body,
    c.prompt_type,
    c.is_deleted,
    EXISTS (
        SELECT 1 FROM moderation_reports mr
        WHERE mr.content_type = 'conversation'
          AND mr.content_id = c.id
          AND mr.status = 'pending'
    ) AS has_pending_report,
    EXISTS (
        SELECT 1 FROM moderation_filtered_messages mfm
        WHERE mfm.content_type = 'conversation'
          AND mfm.content_id = c.id
          AND mfm.layer = 'report'
    ) AS deleted_by_moderator,
    c.deleted_at,
    c.created_at,
    c.updated_at,
    c.last_activity_at,
    u.id        AS author_id,
    u.name      AS author_name,
    u.avatar_url AS author_avatar_url,
    u.about     AS author_about,
    (
        SELECT COUNT(*)
        FROM conversation_messages cm
        WHERE cm.conversation_id = c.id
        AND (
            EXISTS (
                SELECT 1 FROM moderation_filtered_messages mfm
                WHERE mfm.content_type = 'message'
                  AND mfm.content_id = cm.id
                  AND mfm.layer = 'report'
            )
            OR NOT EXISTS (
            SELECT 1 FROM moderation_filtered_messages mfm
            WHERE mfm.content_type = 'message' AND mfm.content_id = cm.id
        ))
    )
    + (
        SELECT COUNT(*)
        FROM message_replies mr
        JOIN conversation_messages cm ON mr.message_id = cm.id
        WHERE cm.conversation_id = c.id
        AND (
            EXISTS (
                SELECT 1 FROM moderation_filtered_messages mfm
                WHERE mfm.content_type = 'message'
                  AND mfm.content_id = cm.id
                  AND mfm.layer = 'report'
            )
            OR NOT EXISTS (
            SELECT 1 FROM moderation_filtered_messages mfm
            WHERE mfm.content_type = 'message' AND mfm.content_id = cm.id
        ))
        AND (
            EXISTS (
                SELECT 1 FROM moderation_filtered_messages mfm
                WHERE mfm.content_type = 'reply'
                  AND mfm.content_id = mr.id
                  AND mfm.layer = 'report'
            )
            OR NOT EXISTS (
            SELECT 1 FROM moderation_filtered_messages mfm
            WHERE mfm.content_type = 'reply' AND mfm.content_id = mr.id
        ))
    )
    AS reply_count,
    (SELECT COUNT(*) FROM conversation_hearts   ch  WHERE ch.conversation_id  = c.id) AS heart_count,
    (SELECT COUNT(*) FROM conversation_participants cp WHERE cp.conversation_id = c.id) AS participant_count
"""

_TIME_WINDOW_SQL: dict[str, str] = {
    'today': "AND c.last_activity_at >= NOW() - INTERVAL '1 day'",
    'week':  "AND c.last_activity_at >= NOW() - INTERVAL '7 days'",
    'month': "AND c.last_activity_at >= NOW() - INTERVAL '30 days'",
    'year':  "AND c.last_activity_at >= NOW() - INTERVAL '365 days'",
    'all':   '',
}

_MESSAGE_COLS = """
    m.id,
    m.conversation_id,
    m.body,
    m.is_deleted,
    EXISTS (
        SELECT 1 FROM moderation_reports mr
        WHERE mr.content_type = 'message'
          AND mr.content_id = m.id
          AND mr.status = 'pending'
    ) AS has_pending_report,
    EXISTS (
        SELECT 1 FROM moderation_filtered_messages mfm
        WHERE mfm.content_type = 'message'
          AND mfm.content_id = m.id
          AND mfm.layer = 'report'
    ) AS deleted_by_moderator,
    m.deleted_at,
    m.created_at,
    m.updated_at,
    u.id         AS author_id,
    u.name       AS author_name,
    u.avatar_url  AS author_avatar_url,
    u.about      AS author_about,
    (SELECT COUNT(*) FROM message_hearts mh WHERE mh.message_id = m.id) AS heart_count,
    (
        SELECT COUNT(*)
        FROM message_replies mr
        WHERE mr.message_id = m.id
        AND (
            EXISTS (
                SELECT 1 FROM moderation_filtered_messages mfm
                WHERE mfm.content_type = 'reply'
                  AND mfm.content_id = mr.id
                  AND mfm.layer = 'report'
            )
            OR NOT EXISTS (
            SELECT 1 FROM moderation_filtered_messages mfm
            WHERE mfm.content_type = 'reply' AND mfm.content_id = mr.id
        ))
    ) AS reply_count
"""

_REPLY_COLS = """
    r.id,
    r.message_id,
    r.body,
    r.is_deleted,
    EXISTS (
        SELECT 1 FROM moderation_reports mr
        WHERE mr.content_type = 'reply'
          AND mr.content_id = r.id
          AND mr.status = 'pending'
    ) AS has_pending_report,
    EXISTS (
        SELECT 1 FROM moderation_filtered_messages mfm
        WHERE mfm.content_type = 'reply'
          AND mfm.content_id = r.id
          AND mfm.layer = 'report'
    ) AS deleted_by_moderator,
    r.deleted_at,
    r.created_at,
    r.updated_at,
    u.id         AS author_id,
    u.name       AS author_name,
    u.avatar_url  AS author_avatar_url,
    u.about      AS author_about,
    (SELECT COUNT(*) FROM reply_hearts rh WHERE rh.reply_id = r.id) AS heart_count
"""


async def list_conversations(
    conn: asyncpg.Connection,
    community_id: UUID,
    user_id: UUID,
    sort: Literal['recent', 'popular', 'active'] = 'recent',
    time_window: Literal['today', 'week', 'month', 'year', 'all'] = 'all',
    cursor_id: UUID | None = None,
    cursor_last_activity_at: datetime | None = None,
    cursor_heart_count: int | None = None,
    cursor_reply_count: int | None = None,
) -> list[asyncpg.Record]:
    params: list = [community_id, user_id]
    i = 3

    time_filter = _TIME_WINDOW_SQL[time_window]

    cursor_condition = ''
    if sort == 'recent' and cursor_last_activity_at and cursor_id:
        cursor_condition = f'WHERE (last_activity_at, id) < (${i}, ${i + 1})'
        params.extend([cursor_last_activity_at, cursor_id])
        i += 2
    elif sort == 'popular' and cursor_heart_count is not None and cursor_id:
        cursor_condition = f'WHERE (heart_count, id) < (${i}, ${i + 1})'
        params.extend([cursor_heart_count, cursor_id])
        i += 2
    elif sort == 'active' and cursor_reply_count is not None and cursor_id:
        cursor_condition = f'WHERE (reply_count, id) < (${i}, ${i + 1})'
        params.extend([cursor_reply_count, cursor_id])
        i += 2

    if sort == 'popular':
        order_by = 'heart_count DESC, id DESC'
    elif sort == 'active':
        order_by = 'reply_count DESC, id DESC'
    else:
        order_by = 'last_activity_at DESC, id DESC'

    query = f"""
        WITH convs AS (
            SELECT
                {_CONVERSATION_COLS},
                EXISTS (
                    SELECT 1 FROM conversation_hearts ch
                    WHERE ch.conversation_id = c.id AND ch.user_id = $2
                ) AS is_hearted
            FROM conversations c
            LEFT JOIN public.users u ON u.id = c.author_id
            WHERE c.community_id = $1
            AND (
                EXISTS (
                    SELECT 1 FROM moderation_filtered_messages mfm
                    WHERE mfm.content_type = 'conversation'
                      AND mfm.content_id = c.id
                      AND mfm.layer = 'report'
                )
                OR NOT EXISTS (
                SELECT 1 FROM moderation_filtered_messages mfm
                WHERE mfm.content_type = 'conversation' AND mfm.content_id = c.id
            ))
            {time_filter}
        )
        SELECT * FROM convs
        {cursor_condition}
        ORDER BY {order_by}
        LIMIT ${i}
    """
    params.append(CONVERSATIONS_PAGE_LIMIT)
    return await conn.fetch(query, *params)


async def get_conversation(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    user_id: UUID,
) -> asyncpg.Record | None:
    query = f"""
        SELECT
            {_CONVERSATION_COLS},
            EXISTS (
                SELECT 1 FROM conversation_hearts ch
                WHERE ch.conversation_id = c.id AND ch.user_id = $2
            ) AS is_hearted
        FROM conversations c
        LEFT JOIN public.users u ON u.id = c.author_id
        WHERE c.id = $1
        AND (
            EXISTS (
                SELECT 1 FROM moderation_filtered_messages mfm
                WHERE mfm.content_type = 'conversation'
                  AND mfm.content_id = c.id
                  AND mfm.layer = 'report'
            )
            OR NOT EXISTS (
            SELECT 1 FROM moderation_filtered_messages mfm
            WHERE mfm.content_type = 'conversation' AND mfm.content_id = c.id
        ))
    """
    return await conn.fetchrow(query, conversation_id, user_id)


async def list_messages(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    user_id: UUID,
    cursor_id: UUID | None = None,
    cursor_created_at: datetime | None = None,
) -> list[asyncpg.Record]:
    conditions = [
        "m.conversation_id = $1",
        """
        (
            EXISTS (
                SELECT 1 FROM moderation_filtered_messages mfm
                WHERE mfm.content_type = 'message'
                  AND mfm.content_id = m.id
                  AND mfm.layer = 'report'
            )
            OR NOT EXISTS (
            SELECT 1 FROM moderation_filtered_messages mfm
            WHERE mfm.content_type = 'message' AND mfm.content_id = m.id
        ))
        """,
    ]
    params: list = [conversation_id, user_id]
    i = 3

    if cursor_created_at and cursor_id:
        conditions.append(f"(m.created_at, m.id) > (${i}, ${i + 1})")
        params.extend([cursor_created_at, cursor_id])
        i += 2

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT
            {_MESSAGE_COLS},
            EXISTS (
                SELECT 1 FROM message_hearts mh
                WHERE mh.message_id = m.id AND mh.user_id = $2
            ) AS is_hearted
        FROM conversation_messages m
        LEFT JOIN public.users u ON u.id = m.author_id
        WHERE {where_clause}
        ORDER BY m.created_at ASC, m.id ASC
        LIMIT ${i}
    """
    params.append(MESSAGES_PAGE_LIMIT)
    return await conn.fetch(query, *params)


async def list_participants(
    conn: asyncpg.Connection,
    conversation_id: UUID,
) -> list[asyncpg.Record]:
    query = """
        SELECT
            u.id,
            u.name,
            u.avatar_url,
            cp.first_joined_at,
            cp.last_active_at
        FROM conversation_participants cp
        JOIN public.users u ON u.id = cp.user_id
        WHERE cp.conversation_id = $1
        ORDER BY cp.first_joined_at ASC
    """
    return await conn.fetch(query, conversation_id)


async def insert_conversation(
    conn: asyncpg.Connection,
    community_id: UUID,
    author_id: UUID,
    title: str,
    body: str,
    prompt_type: str | None,
) -> asyncpg.Record:
    query = """
        INSERT INTO conversations (community_id, author_id, title, body, prompt_type)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
    """
    return await conn.fetchrow(query, community_id, author_id, title, body, prompt_type)


async def upsert_participant(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    user_id: UUID,
) -> None:
    query = """
        INSERT INTO conversation_participants (conversation_id, user_id, first_joined_at, last_active_at)
        VALUES ($1, $2, NOW(), NOW())
        ON CONFLICT (conversation_id, user_id)
        DO UPDATE SET last_active_at = NOW()
    """
    await conn.execute(query, conversation_id, user_id)


async def insert_message(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    author_id: UUID,
    body: str,
) -> asyncpg.Record:
    query = """
        INSERT INTO conversation_messages (conversation_id, author_id, body)
        VALUES ($1, $2, $3)
        RETURNING id
    """
    return await conn.fetchrow(query, conversation_id, author_id, body)


async def touch_conversation(
    conn: asyncpg.Connection,
    conversation_id: UUID,
) -> None:
    query = """
        UPDATE conversations
        SET last_activity_at = NOW(), updated_at = NOW()
        WHERE id = $1
    """
    await conn.execute(query, conversation_id)


async def _assert_content_active(
    conn: asyncpg.Connection,
    table: str,
    content_id: UUID,
    label: str,
) -> None:
    """Raise 404 if the target row is missing or soft-deleted.

    `table` is always a trusted literal supplied by the caller (never user
    input), so the f-string interpolation is safe.
    """
    exists = await conn.fetchval(
        f"SELECT EXISTS(SELECT 1 FROM {table} WHERE id = $1 AND NOT is_deleted)",
        content_id,
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label} not found.",
        )


async def heart_conversation(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    user_id: UUID,
) -> None:
    await _assert_content_active(
        conn, "conversations", conversation_id, "Conversation"
    )
    await conn.execute(
        """
        INSERT INTO conversation_hearts (conversation_id, user_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        """,
        conversation_id,
        user_id,
    )


async def unheart_conversation(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    user_id: UUID,
) -> None:
    await conn.execute(
        "DELETE FROM conversation_hearts WHERE conversation_id = $1 AND user_id = $2",
        conversation_id,
        user_id,
    )


async def heart_message(
    conn: asyncpg.Connection,
    message_id: UUID,
    user_id: UUID,
) -> None:
    await _assert_content_active(
        conn, "conversation_messages", message_id, "Message"
    )
    await conn.execute(
        """
        INSERT INTO message_hearts (message_id, user_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        """,
        message_id,
        user_id,
    )


async def unheart_message(
    conn: asyncpg.Connection,
    message_id: UUID,
    user_id: UUID,
) -> None:
    await conn.execute(
        "DELETE FROM message_hearts WHERE message_id = $1 AND user_id = $2",
        message_id,
        user_id,
    )


async def _soft_delete_owned_content(
    conn: asyncpg.Connection,
    table: str,
    content_id: UUID,
    user_id: UUID,
    label: str,
) -> None:
    record = await conn.fetchrow(
        f"SELECT author_id, is_deleted FROM {table} WHERE id = $1",
        content_id,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label} not found.",
        )
    if record["author_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You can only delete your own {label.lower()}.",
        )
    if record["is_deleted"]:
        return

    await conn.execute(
        f"""
        UPDATE {table}
        SET is_deleted = TRUE,
            deleted_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
        """,
        content_id,
    )


async def delete_conversation(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    user_id: UUID,
) -> None:
    await _soft_delete_owned_content(
        conn, "conversations", conversation_id, user_id, "Conversation"
    )


async def delete_message(
    conn: asyncpg.Connection,
    message_id: UUID,
    user_id: UUID,
) -> None:
    await _soft_delete_owned_content(
        conn, "conversation_messages", message_id, user_id, "Message"
    )


async def delete_reply(
    conn: asyncpg.Connection,
    reply_id: UUID,
    user_id: UUID,
) -> None:
    await _soft_delete_owned_content(
        conn, "message_replies", reply_id, user_id, "Reply"
    )


def _author(record: asyncpg.Record) -> AuthorInfo | None:
    if record["author_id"] is None:
        return None
    return AuthorInfo(
        id=record["author_id"],
        name=record["author_name"],
        avatar_url=record["author_avatar_url"],
        about=record["author_about"],
    )


def record_to_conversation(record: asyncpg.Record) -> ConversationResponse:
    is_deleted = record["is_deleted"]
    placeholder = (
        REMOVED_BY_MODERATOR
        if record["deleted_by_moderator"]
        else REMOVED_BY_ORIGINAL_POSTER
    )
    return ConversationResponse(
        id=record["id"],
        community_id=record["community_id"],
        author=_author(record),
        title=REMOVED_CONVERSATION_TITLE if is_deleted else record["title"],
        body=placeholder if is_deleted else record["body"],
        prompt_type=record["prompt_type"],
        reply_count=record["reply_count"],
        heart_count=record["heart_count"],
        participant_count=record["participant_count"],
        is_hearted=record["is_hearted"],
        is_deleted=is_deleted,
        has_pending_report=record["has_pending_report"],
        deleted_at=record["deleted_at"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        last_activity_at=record["last_activity_at"],
    )


def record_to_message(record: asyncpg.Record) -> MessageResponse:
    is_deleted = record["is_deleted"]
    placeholder = (
        REMOVED_BY_MODERATOR
        if record["deleted_by_moderator"]
        else REMOVED_BY_ORIGINAL_POSTER
    )
    return MessageResponse(
        id=record["id"],
        conversation_id=record["conversation_id"],
        author=_author(record),
        body=placeholder if is_deleted else record["body"],
        reply_count=record["reply_count"],
        heart_count=record["heart_count"],
        is_hearted=record["is_hearted"],
        is_deleted=is_deleted,
        has_pending_report=record["has_pending_report"],
        deleted_at=record["deleted_at"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def record_to_reply(record: asyncpg.Record) -> ReplyResponse:
    is_deleted = record["is_deleted"]
    placeholder = (
        REMOVED_BY_MODERATOR
        if record["deleted_by_moderator"]
        else REMOVED_BY_ORIGINAL_POSTER
    )
    return ReplyResponse(
        id=record["id"],
        message_id=record["message_id"],
        author=_author(record),
        body=placeholder if is_deleted else record["body"],
        heart_count=record["heart_count"],
        is_hearted=record["is_hearted"],
        is_deleted=is_deleted,
        has_pending_report=record["has_pending_report"],
        deleted_at=record["deleted_at"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def record_to_participant(record: asyncpg.Record) -> ParticipantResponse:
    return ParticipantResponse(
        id=record["id"],
        name=record["name"],
        avatar_url=record["avatar_url"],
        first_joined_at=record["first_joined_at"],
        last_active_at=record["last_active_at"],
    )


async def list_replies(
    conn: asyncpg.Connection,
    message_id: UUID,
    user_id: UUID,
    cursor_id: UUID | None = None,
    cursor_heart_count: int | None = None,
) -> list[asyncpg.Record]:
    params: list = [message_id, user_id]
    i = 3

    cursor_condition = ''
    if cursor_heart_count is not None and cursor_id:
        cursor_condition = f'WHERE (heart_count, id) < (${i}, ${i + 1})'
        params.extend([cursor_heart_count, cursor_id])
        i += 2

    query = f"""
        WITH ranked AS (
            SELECT
                {_REPLY_COLS},
                EXISTS (
                    SELECT 1 FROM reply_hearts rh
                    WHERE rh.reply_id = r.id AND rh.user_id = $2
                ) AS is_hearted
            FROM message_replies r
            LEFT JOIN public.users u ON u.id = r.author_id
            WHERE r.message_id = $1
            AND (
                EXISTS (
                    SELECT 1 FROM moderation_filtered_messages mfm
                    WHERE mfm.content_type = 'reply'
                      AND mfm.content_id = r.id
                      AND mfm.layer = 'report'
                )
                OR NOT EXISTS (
                SELECT 1 FROM moderation_filtered_messages mfm
                WHERE mfm.content_type = 'reply' AND mfm.content_id = r.id
            ))
        )
        SELECT * FROM ranked
        {cursor_condition}
        ORDER BY heart_count DESC, id DESC
        LIMIT ${i}
    """
    params.append(REPLIES_PAGE_LIMIT)
    return await conn.fetch(query, *params)


async def insert_reply(
    conn: asyncpg.Connection,
    message_id: UUID,
    author_id: UUID,
    body: str,
) -> asyncpg.Record:
    query = """
        INSERT INTO message_replies (message_id, author_id, body)
        VALUES ($1, $2, $3)
        RETURNING id
    """
    return await conn.fetchrow(query, message_id, author_id, body)


async def heart_reply(
    conn: asyncpg.Connection,
    reply_id: UUID,
    user_id: UUID,
) -> None:
    await _assert_content_active(conn, "message_replies", reply_id, "Reply")
    await conn.execute(
        """
        INSERT INTO reply_hearts (reply_id, user_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        """,
        reply_id,
        user_id,
    )


async def unheart_reply(
    conn: asyncpg.Connection,
    reply_id: UUID,
    user_id: UUID,
) -> None:
    await conn.execute(
        "DELETE FROM reply_hearts WHERE reply_id = $1 AND user_id = $2",
        reply_id,
        user_id,
    )


async def reply_to_message(
    conn: asyncpg.Connection,
    message_id: UUID,
    author_id: UUID,
    body: str,
) -> ReplyResponse:
    exists = await conn.fetchval(
        """
        SELECT EXISTS(
            SELECT 1
            FROM conversation_messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id = $1 AND NOT m.is_deleted AND NOT c.is_deleted
        )
        """,
        message_id,
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found.",
        )

    row = await insert_reply(conn, message_id, author_id, body)
    record = await conn.fetchrow(
        f"""
        SELECT
            {_REPLY_COLS},
            FALSE AS is_hearted
        FROM message_replies r
        LEFT JOIN public.users u ON u.id = r.author_id
        WHERE r.id = $1
        """,
        row["id"],
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch created reply.",
        )
    return record_to_reply(record)


async def start_conversation(
    conn: asyncpg.Connection,
    community_id: UUID,
    author_id: UUID,
    title: str,
    body: str,
    prompt_type: str | None,
) -> ConversationResponse:
    exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM communities WHERE id = $1)", community_id
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Community not found.",
        )

    async with conn.transaction():
        row = await insert_conversation(conn, community_id, author_id, title, body, prompt_type)
        await upsert_participant(conn, row["id"], author_id)

    full = await get_conversation(conn, row["id"], author_id)
    return record_to_conversation(full)


async def reply_to_conversation(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    author_id: UUID,
    body: str,
) -> MessageResponse:
    exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM conversations WHERE id = $1 AND NOT is_deleted)",
        conversation_id,
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    async with conn.transaction():
        row = await insert_message(conn, conversation_id, author_id, body)
        await touch_conversation(conn, conversation_id)
        await upsert_participant(conn, conversation_id, author_id)

    # Fetch the new message by id — scanning the first page of list_messages
    # misses it once the conversation has MESSAGES_PAGE_LIMIT+ messages (it
    # sorts last by created_at).
    record = await conn.fetchrow(
        f"""
        SELECT
            {_MESSAGE_COLS},
            FALSE AS is_hearted
        FROM conversation_messages m
        LEFT JOIN public.users u ON u.id = m.author_id
        WHERE m.id = $1
        """,
        row["id"],
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch created message.",
        )
    return record_to_message(record)
