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


_TOXICITY_SCORE_TABLES: dict[ContentType, str] = {
    ContentType.MESSAGE: "conversation_messages",
    ContentType.REPLY: "message_replies",
}


async def record_toxicity_score(
    conn: asyncpg.Connection,
    content_type: ContentType,
    content_id: UUID,
    score: float,
) -> None:
    """Write the toxicity model score back to the source row.

    Only messages and replies have this column; conversations are skipped.
    The score is written regardless of whether the content was flagged so
    borderline content remains visible for review.
    """
    table = _TOXICITY_SCORE_TABLES.get(content_type)
    if table is None:
        return
    await conn.execute(
        f"UPDATE {table} SET toxicity_score = $1 WHERE id = $2",
        score,
        content_id,
    )


async def soft_delete_content(
    conn: asyncpg.Connection,
    content_type: ContentType,
    content_id: UUID,
    deleted_by_moderator: bool = False,
) -> None:
    """Hide a flagged row from all reads without losing the record."""
    table = _CONTENT_TABLES[content_type]
    await conn.execute(
        f"""
        UPDATE {table}
        SET is_deleted = TRUE,
            deleted_at = NOW(),
            deleted_by_moderator = $2
        WHERE id = $1
        """,
        content_id,
        deleted_by_moderator,
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
        RETURNING id, created_at, expires_at
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
            SET reason = EXCLUDED.reason,
                status = 'pending',
                created_at = NOW()
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


# ── User reports ───────────────────────────────────────────────────────────


async def insert_user_report(
    conn: asyncpg.Connection,
    reported_id: UUID,
    reporter_id: UUID,
    reason: str | None,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO user_reports (reported_id, reporter_id, reason)
        VALUES ($1, $2, $3)
        ON CONFLICT (reported_id, reporter_id) DO UPDATE
            SET reason = EXCLUDED.reason,
                status = 'pending',
                created_at = NOW()
        RETURNING id, reported_id, status, created_at
        """,
        reported_id,
        reporter_id,
        reason,
    )


# ── Admin queries ──────────────────────────────────────────────────────────


async def list_content_reports(
    conn: asyncpg.Connection,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT r.id, r.content_type, r.content_id,
               r.reporter_id, u.name AS reporter_name,
               r.reason, r.status, r.created_at
        FROM moderation_reports r
        LEFT JOIN public.users u ON u.id = r.reporter_id
        WHERE ($1::text IS NULL OR r.status = $1)
        ORDER BY r.created_at DESC
        LIMIT $2 OFFSET $3
        """,
        status_filter,
        limit,
        offset,
    )


async def list_user_reports(
    conn: asyncpg.Connection,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT r.id,
               r.reported_id, ru.name AS reported_name,
               r.reporter_id, u.name AS reporter_name,
               r.reason, r.status, r.created_at
        FROM user_reports r
        LEFT JOIN public.users u  ON u.id  = r.reporter_id
        LEFT JOIN public.users ru ON ru.id = r.reported_id
        WHERE ($1::text IS NULL OR r.status = $1)
        ORDER BY r.created_at DESC
        LIMIT $2 OFFSET $3
        """,
        status_filter,
        limit,
        offset,
    )


async def update_content_report_status(
    conn: asyncpg.Connection,
    report_id: UUID,
    new_status: str,
) -> bool:
    result = await conn.execute(
        "UPDATE moderation_reports SET status = $1 WHERE id = $2",
        new_status,
        report_id,
    )
    return result.split()[-1] != "0"


async def get_content_report_for_action(
    conn: asyncpg.Connection,
    report_id: UUID,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, content_type, content_id, reason, status
        FROM moderation_reports
        WHERE id = $1
        FOR UPDATE
        """,
        report_id,
    )


async def get_content_for_moderator_action(
    conn: asyncpg.Connection,
    content_type: ContentType,
    content_id: UUID,
) -> asyncpg.Record | None:
    if content_type == ContentType.CONVERSATION:
        return await conn.fetchrow(
            """
            SELECT c.author_id, c.community_id, c.is_deleted,
                   CONCAT(c.title, E'\n\n', c.body) AS original_text
            FROM conversations c
            WHERE c.id = $1
            """,
            content_id,
        )
    if content_type == ContentType.MESSAGE:
        return await conn.fetchrow(
            """
            SELECT m.author_id, c.community_id, m.is_deleted,
                   m.body AS original_text
            FROM conversation_messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id = $1
            """,
            content_id,
        )
    return await conn.fetchrow(
        """
        SELECT r.author_id, c.community_id, r.is_deleted,
               r.body AS original_text
        FROM message_replies r
        JOIN conversation_messages m ON m.id = r.message_id
        JOIN conversations c ON c.id = m.conversation_id
        WHERE r.id = $1
        """,
        content_id,
    )


async def filtered_message_exists(
    conn: asyncpg.Connection,
    content_type: ContentType,
    content_id: UUID,
    layer: ModerationLayer,
) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS(
              SELECT 1
              FROM moderation_filtered_messages
              WHERE content_type = $1
                AND content_id = $2
                AND layer = $3
            )
            """,
            content_type.value,
            content_id,
            layer.value,
        )
    )


async def update_user_report_status(
    conn: asyncpg.Connection,
    report_id: UUID,
    new_status: str,
) -> bool:
    result = await conn.execute(
        "UPDATE user_reports SET status = $1 WHERE id = $2",
        new_status,
        report_id,
    )
    return result.split()[-1] != "0"


async def get_user_report_for_action(
    conn: asyncpg.Connection,
    report_id: UUID,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, reported_id, reason, status
        FROM user_reports
        WHERE id = $1
        FOR UPDATE
        """,
        report_id,
    )


async def list_filtered_messages_admin(
    conn: asyncpg.Connection,
    limit: int,
    offset: int,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT f.id, f.content_type, f.content_id,
               f.author_id, u.name AS author_name,
               f.community_id, f.original_text,
               f.layer, f.reason, f.score, f.created_at
        FROM moderation_filtered_messages f
        LEFT JOIN public.users u ON u.id = f.author_id
        ORDER BY f.created_at DESC
        LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )


async def list_active_bans_admin(
    conn: asyncpg.Connection,
    limit: int,
    offset: int,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT b.id, b.user_id, u.name AS user_name,
               b.reason, b.created_at, b.expires_at
        FROM moderation_bans b
        LEFT JOIN public.users u ON u.id = b.user_id
        WHERE b.expires_at > NOW()
        ORDER BY b.expires_at ASC
        LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )


async def get_content_context_admin(
    conn: asyncpg.Connection,
    content_type: str,
    content_id: UUID,
) -> dict | None:
    context_ids = await conn.fetchrow(
        """
        SELECT
          CASE
            WHEN $1 = 'conversation' THEN $2
            WHEN $1 = 'message' THEN (
                SELECT conversation_id FROM conversation_messages WHERE id = $2
            )
            WHEN $1 = 'reply' THEN (
                SELECT m.conversation_id
                FROM message_replies r
                JOIN conversation_messages m ON m.id = r.message_id
                WHERE r.id = $2
            )
          END AS conversation_id,
          CASE
            WHEN $1 = 'message' THEN $2
            WHEN $1 = 'reply' THEN (
                SELECT message_id FROM message_replies WHERE id = $2
            )
          END AS message_id
        """,
        content_type,
        content_id,
    )
    if context_ids is None or context_ids["conversation_id"] is None:
        return None

    conversation_id = context_ids["conversation_id"]
    message_id = context_ids["message_id"]

    conversation = await conn.fetchrow(
        """
        SELECT c.id, c.community_id, c.title, c.body, c.author_id,
               u.name AS author_name, c.is_deleted, c.created_at
        FROM conversations c
        LEFT JOIN public.users u ON u.id = c.author_id
        WHERE c.id = $1
        """,
        conversation_id,
    )
    if conversation is None:
        return None

    messages = []
    replies = []
    if message_id is not None:
        messages = await conn.fetch(
            """
            SELECT m.id, m.conversation_id, m.body, m.author_id,
                   u.name AS author_name, m.is_deleted, m.created_at,
                   (m.id = $2 AND $3 = 'message') AS is_target,
                   (m.id = $2) AS is_focus
            FROM conversation_messages m
            LEFT JOIN public.users u ON u.id = m.author_id
            WHERE m.conversation_id = $1
            ORDER BY
              CASE WHEN m.id = $2 THEN 0 ELSE 1 END,
              m.created_at ASC
            LIMIT 200
            """,
            conversation_id,
            message_id,
            content_type,
        )
        message_ids = [m["id"] for m in messages]
        if message_ids:
            replies = await conn.fetch(
                """
                SELECT r.id, r.message_id, r.body, r.author_id,
                       u.name AS author_name, r.is_deleted, r.created_at,
                       (r.id = $2) AS is_target
                FROM message_replies r
                LEFT JOIN public.users u ON u.id = r.author_id
                WHERE r.message_id = ANY($1::uuid[])
                ORDER BY r.created_at ASC
                """,
                message_ids,
                content_id if content_type == "reply" else None,
            )

    return {
        "conversation": dict(conversation),
        "messages": [dict(m) for m in messages],
        "replies": [dict(r) for r in replies],
        "target": {"content_type": content_type, "content_id": content_id},
    }


async def get_user_activity_context_admin(
    conn: asyncpg.Connection,
    user_id: UUID,
    limit: int,
) -> dict | None:
    user = await conn.fetchrow(
        "SELECT id, name, city, province, about, avatar_url FROM public.users WHERE id = $1",
        user_id,
    )
    if user is None:
        return None

    activity = await conn.fetch(
        """
        SELECT *
        FROM (
            SELECT 'post' AS activity_type, c.id, c.body AS text,
                   c.title AS context_title, c.community_id,
                   c.created_at, c.is_deleted
            FROM conversations c
            WHERE c.author_id = $1

            UNION ALL

            SELECT 'message' AS activity_type, m.id, m.body AS text,
                   c.title AS context_title, c.community_id,
                   m.created_at, m.is_deleted
            FROM conversation_messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.author_id = $1

            UNION ALL

            SELECT 'reply' AS activity_type, r.id, r.body AS text,
                   c.title AS context_title, c.community_id,
                   r.created_at, r.is_deleted
            FROM message_replies r
            JOIN conversation_messages m ON m.id = r.message_id
            JOIN conversations c ON c.id = m.conversation_id
            WHERE r.author_id = $1
        ) recent_activity
        ORDER BY created_at DESC
        LIMIT $2
        """,
        user_id,
        limit,
    )

    return {
        "user": dict(user),
        "activity": [dict(row) for row in activity],
    }


async def lift_ban(
    conn: asyncpg.Connection,
    ban_id: UUID,
) -> bool:
    result = await conn.execute(
        "UPDATE moderation_bans SET expires_at = NOW() WHERE id = $1",
        ban_id,
    )
    return result.split()[-1] != "0"
