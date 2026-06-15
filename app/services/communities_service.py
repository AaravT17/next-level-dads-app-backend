from datetime import datetime
from fastapi import HTTPException, status
from uuid import UUID
import asyncpg

from app.config.constants import CONVERSATIONS_PAGE_LIMIT
from app.models.communities import (
    AuthorInfo,
    ConversationResponse,
    MessageResponse,
    ParticipantResponse,
)

_CONVERSATION_COLS = """
    c.id,
    c.community_id,
    c.title,
    c.body,
    c.prompt_type,
    c.created_at,
    c.updated_at,
    c.last_activity_at,
    u.id        AS author_id,
    u.name      AS author_name,
    u.avatar_url AS author_avatar_url,
    u.about     AS author_about,
    (SELECT COUNT(*) FROM conversation_messages cm  WHERE cm.conversation_id  = c.id) AS reply_count,
    (SELECT COUNT(*) FROM conversation_hearts   ch  WHERE ch.conversation_id  = c.id) AS heart_count,
    (SELECT COUNT(*) FROM conversation_participants cp WHERE cp.conversation_id = c.id) AS participant_count
"""

_MESSAGE_COLS = """
    m.id,
    m.conversation_id,
    m.body,
    m.created_at,
    m.updated_at,
    u.id         AS author_id,
    u.name       AS author_name,
    u.avatar_url  AS author_avatar_url,
    u.about      AS author_about,
    (SELECT COUNT(*) FROM message_hearts mh WHERE mh.message_id = m.id) AS heart_count
"""


async def list_conversations(
    conn: asyncpg.Connection,
    community_id: UUID,
    user_id: UUID,
    cursor_id: UUID | None = None,
    cursor_last_activity_at: datetime | None = None,
) -> list[asyncpg.Record]:
    conditions = ["c.community_id = $1"]
    params: list = [community_id, user_id]
    i = 3

    if cursor_last_activity_at and cursor_id:
        conditions.append(f"(c.last_activity_at, c.id) < (${i}, ${i + 1})")
        params.extend([cursor_last_activity_at, cursor_id])
        i += 2

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT
            {_CONVERSATION_COLS},
            EXISTS (
                SELECT 1 FROM conversation_hearts ch
                WHERE ch.conversation_id = c.id AND ch.user_id = $2
            ) AS is_hearted
        FROM conversations c
        LEFT JOIN public.users u ON u.id = c.author_id
        WHERE {where_clause}
        ORDER BY c.last_activity_at DESC, c.id DESC
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
    """
    return await conn.fetchrow(query, conversation_id, user_id)


async def list_messages(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    user_id: UUID,
) -> list[asyncpg.Record]:
    query = f"""
        SELECT
            {_MESSAGE_COLS},
            EXISTS (
                SELECT 1 FROM message_hearts mh
                WHERE mh.message_id = m.id AND mh.user_id = $2
            ) AS is_hearted
        FROM conversation_messages m
        LEFT JOIN public.users u ON u.id = m.author_id
        WHERE m.conversation_id = $1
        ORDER BY m.created_at ASC
    """
    return await conn.fetch(query, conversation_id, user_id)


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


async def heart_conversation(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    user_id: UUID,
) -> None:
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
    return ConversationResponse(
        id=record["id"],
        community_id=record["community_id"],
        author=_author(record),
        title=record["title"],
        body=record["body"],
        prompt_type=record["prompt_type"],
        reply_count=record["reply_count"],
        heart_count=record["heart_count"],
        participant_count=record["participant_count"],
        is_hearted=record["is_hearted"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        last_activity_at=record["last_activity_at"],
    )


def record_to_message(record: asyncpg.Record) -> MessageResponse:
    return MessageResponse(
        id=record["id"],
        conversation_id=record["conversation_id"],
        author=_author(record),
        body=record["body"],
        heart_count=record["heart_count"],
        is_hearted=record["is_hearted"],
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
        "SELECT EXISTS(SELECT 1 FROM conversations WHERE id = $1)", conversation_id
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

    records = await list_messages(conn, conversation_id, author_id)
    match = next((r for r in records if r["id"] == row["id"]), None)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch created message.",
        )
    return record_to_message(match)
