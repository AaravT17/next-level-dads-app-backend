"""Data-access layer for moderation tables and soft-deletes."""

from uuid import UUID

import asyncpg

from app.moderation.models import ContentType, ModerationLayer, NotificationType

# Maps a content type to the table whose rows it soft-deletes.
_CONTENT_TABLES: dict[ContentType, str] = {
    ContentType.CONVERSATION: "conversations",
    ContentType.MESSAGE: "conversation_messages",
    ContentType.REPLY: "message_replies",
}


async def content_exists(
    conn: asyncpg.Connection,
    content_type: ContentType,
    content_id: UUID,
) -> bool:
    table = _CONTENT_TABLES[content_type]
    return bool(
        await conn.fetchval(
            f"SELECT EXISTS(SELECT 1 FROM {table} WHERE id = $1 AND NOT is_deleted)",
            content_id,
        )
    )


# Resolves the owning community for each content type (for the audit log).
_COMMUNITY_ID_QUERIES: dict[ContentType, str] = {
    ContentType.CONVERSATION: (
        "SELECT community_id FROM conversations WHERE id = $1"
    ),
    ContentType.MESSAGE: """
        SELECT c.community_id
        FROM conversation_messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE m.id = $1
    """,
    ContentType.REPLY: """
        SELECT c.community_id
        FROM message_replies r
        JOIN conversation_messages m ON m.id = r.message_id
        JOIN conversations c ON c.id = m.conversation_id
        WHERE r.id = $1
    """,
}


async def get_community_id(
    conn: asyncpg.Connection,
    content_type: ContentType,
    content_id: UUID,
) -> UUID | None:
    """Resolve the community a piece of content belongs to (for the audit log)."""
    return await conn.fetchval(_COMMUNITY_ID_QUERIES[content_type], content_id)


async def soft_delete_content(
    conn: asyncpg.Connection,
    content_type: ContentType,
    content_id: UUID,
) -> None:
    """Hide a flagged row from all reads without losing the record."""
    table = _CONTENT_TABLES[content_type]
    await conn.execute(
        f"""
        UPDATE {table}
        SET is_deleted = TRUE, deleted_at = NOW()
        WHERE id = $1
        """,
        content_id,
    )


async def insert_filtered_message(
    conn: asyncpg.Connection,
    content_type: ContentType,
    content_id: UUID,
    author_id: UUID | None,
    community_id: UUID | None,
    original_text: str,
    layer: ModerationLayer,
    reason: str | None,
    score: float | None,
) -> None:
    """Record a removal in the audit log."""
    await conn.execute(
        """
        INSERT INTO moderation_filtered_messages
            (content_type, content_id, author_id, community_id,
             original_text, layer, reason, score)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        content_type.value,
        content_id,
        author_id,
        community_id,
        original_text,
        layer.value,
        reason,
        score,
    )


async def count_recent_auto_removals(
    conn: asyncpg.Connection,
    author_id: UUID,
    window_hours: int,
) -> int:
    """Count an author's auto-filtered removals within the trailing window.

    Excludes report-driven entries — only automated filtering counts toward a
    ban so users cannot get someone banned by mass-reporting. Also resets at the
    author's most recent ban: only removals after the last ban was issued count,
    so a user isn't instantly re-banned by a single removal once a ban expires
    while earlier removals are still inside the window.
    """
    return await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM moderation_filtered_messages
        WHERE author_id = $1
          AND layer <> 'report'
          AND created_at >= NOW() - ($2 || ' hours')::INTERVAL
          AND created_at > COALESCE(
                (SELECT created_at FROM moderation_bans
                 WHERE user_id = $1
                 ORDER BY created_at DESC LIMIT 1),
                '-infinity'::timestamptz
              )
        """,
        author_id,
        str(window_hours),
    )


async def get_active_ban(
    conn: asyncpg.Connection,
    user_id: UUID,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, reason, created_at, expires_at
        FROM moderation_bans
        WHERE user_id = $1 AND expires_at > NOW()
        ORDER BY expires_at DESC
        LIMIT 1
        """,
        user_id,
    )


async def insert_ban(
    conn: asyncpg.Connection,
    user_id: UUID,
    reason: str,
    duration_hours: int,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO moderation_bans (user_id, reason, expires_at)
        VALUES ($1, $2, NOW() + ($3 || ' hours')::INTERVAL)
        RETURNING id, expires_at
        """,
        user_id,
        reason,
        str(duration_hours),
    )


async def insert_report(
    conn: asyncpg.Connection,
    content_type: ContentType,
    content_id: UUID,
    reporter_id: UUID,
    reason: str | None,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO moderation_reports (content_type, content_id, reporter_id, reason)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (content_type, content_id, reporter_id) DO UPDATE
            SET reason = EXCLUDED.reason
        RETURNING id, content_type, content_id, status, created_at
        """,
        content_type.value,
        content_id,
        reporter_id,
        reason,
    )


# ── Notifications ──────────────────────────────────────────────────────────


async def insert_notification(
    conn: asyncpg.Connection,
    user_id: UUID,
    notification_type: NotificationType,
    message: str,
    content_type: ContentType | None = None,
    content_id: UUID | None = None,
    layer: ModerationLayer | None = None,
    reason: str | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO moderation_notifications
            (user_id, type, content_type, content_id, layer, reason, message)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        user_id,
        notification_type.value,
        content_type.value if content_type else None,
        content_id,
        layer.value if layer else None,
        reason,
        message,
    )


async def list_notifications(
    conn: asyncpg.Connection,
    user_id: UUID,
    unread_only: bool,
    limit: int,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT id, type, content_type, content_id, reason, message, is_read, created_at
        FROM moderation_notifications
        WHERE user_id = $1
          AND ($2 = FALSE OR is_read = FALSE)
        ORDER BY created_at DESC
        LIMIT $3
        """,
        user_id,
        unread_only,
        limit,
    )


async def mark_notification_read(
    conn: asyncpg.Connection,
    user_id: UUID,
    notification_id: UUID,
) -> bool:
    """Mark one notification read; returns False if it isn't the user's."""
    result = await conn.execute(
        """
        UPDATE moderation_notifications
        SET is_read = TRUE
        WHERE id = $1 AND user_id = $2
        """,
        notification_id,
        user_id,
    )
    # asyncpg returns a status like "UPDATE 1"; the last token is the row count.
    return result.split()[-1] != "0"


async def mark_all_notifications_read(
    conn: asyncpg.Connection,
    user_id: UUID,
) -> None:
    await conn.execute(
        """
        UPDATE moderation_notifications
        SET is_read = TRUE
        WHERE user_id = $1 AND is_read = FALSE
        """,
        user_id,
    )
