"""Moderation orchestration: ban enforcement, layered filtering, reporting.

The two filtering layers run from a background task (see `moderate_content`),
so posting stays instant for the user. The fast ban check (`assert_not_banned`)
runs inline on the request path before content is inserted.
"""

import logging
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.config.constants import (
    MODERATION_BAN_DURATION_HOURS,
    MODERATION_BAN_THRESHOLD,
    MODERATION_BAN_WINDOW_HOURS,
    MODERATION_NOTIFICATIONS_PAGE_LIMIT,
)
from app.moderation import repository as repo
from app.moderation.messages import build_ban_message, build_removal_message
from app.moderation.models import (
    ContentType,
    ModerationLayer,
    ModerationResult,
    NotificationType,
)
from app.moderation.profanity_filter import check_profanity
from app.moderation.toxicity import check_toxicity

logger = logging.getLogger(__name__)


async def get_active_ban(
    conn: asyncpg.Connection, user_id: UUID
) -> asyncpg.Record | None:
    return await repo.get_active_ban(conn, user_id)


async def assert_not_banned(conn: asyncpg.Connection, user_id: UUID) -> None:
    """Reject a write from a user with an active temporary ban (HTTP 403)."""
    ban = await repo.get_active_ban(conn, user_id)
    if ban is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": (
                    "You are temporarily banned from posting due to repeated "
                    "removed messages."
                ),
                "expires_at": ban["expires_at"].isoformat(),
            },
        )


async def _classify(text: str) -> ModerationResult:
    """Run the moderation layers in order, stopping at the first hit.

    Cheap local layer first, network classifier second.
    """
    profanity = check_profanity(text)
    if profanity.flagged:
        return profanity
    return await check_toxicity(text)


async def _maybe_ban(
    conn: asyncpg.Connection,
    author_id: UUID,
) -> None:
    """Apply a temporary ban once an author crosses the removal threshold."""
    removals = await repo.count_recent_auto_removals(
        conn, author_id, MODERATION_BAN_WINDOW_HOURS
    )
    if removals < MODERATION_BAN_THRESHOLD:
        return

    # Don't stack bans — skip if one is already active.
    if await repo.get_active_ban(conn, author_id) is not None:
        return

    reason = (
        f"{removals} messages removed within {MODERATION_BAN_WINDOW_HOURS}h"
    )
    ban = await repo.insert_ban(
        conn, author_id, reason, MODERATION_BAN_DURATION_HOURS
    )
    await repo.insert_notification(
        conn,
        author_id,
        NotificationType.TEMPORARY_BAN,
        build_ban_message(MODERATION_BAN_DURATION_HOURS),
    )
    logger.info(
        "Temporary ban applied to user %s until %s (%s)",
        author_id,
        ban["expires_at"],
        reason,
    )


async def moderate_content(
    pool: asyncpg.Pool,
    content_type: ContentType,
    content_id: UUID,
    author_id: UUID,
    community_id: UUID | None,
    text: str,
) -> None:
    """Background-task entrypoint: filter one piece of content and act on it.

    Acquires its own connection because the request's connection is already
    released by the time the background task runs. Never raises — failures are
    logged so they cannot surface to the (already-sent) response.
    """
    try:
        result = await _classify(text)
        if not result.flagged:
            return

        layer = result.layer or ModerationLayer.PROFANITY
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Messages/replies are scheduled without a community id; resolve
                # it here so the audit log keeps community attribution.
                if community_id is None:
                    community_id = await repo.get_community_id(
                        conn, content_type, content_id
                    )
                await repo.soft_delete_content(conn, content_type, content_id)
                await repo.insert_filtered_message(
                    conn,
                    content_type,
                    content_id,
                    author_id,
                    community_id,
                    text,
                    layer,
                    result.reason,
                    result.score,
                )
                await repo.insert_notification(
                    conn,
                    author_id,
                    NotificationType.CONTENT_REMOVED,
                    build_removal_message(content_type, layer),
                    content_type=content_type,
                    content_id=content_id,
                    layer=layer,
                    reason=result.reason,
                )
                # A ban may add a second notification.
                await _maybe_ban(conn, author_id)

        logger.info(
            "Removed %s %s by user %s (layer=%s reason=%s score=%s)",
            content_type.value,
            content_id,
            author_id,
            result.layer.value if result.layer else None,
            result.reason,
            result.score,
        )
    except Exception:  # noqa: BLE001 - background task must never propagate
        logger.exception(
            "Moderation failed for %s %s", content_type.value, content_id
        )


async def report_content(
    conn: asyncpg.Connection,
    reporter_id: UUID,
    content_type: ContentType,
    content_id: UUID,
    reason: str | None,
) -> asyncpg.Record:
    """Record a user report for manual review (does not auto-remove content)."""
    if not await repo.content_exists(conn, content_type, content_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The content you are trying to report no longer exists.",
        )
    return await repo.insert_report(
        conn, content_type, content_id, reporter_id, reason
    )


# ── Notifications ──────────────────────────────────────────────────────────


async def list_notifications(
    conn: asyncpg.Connection,
    user_id: UUID,
    unread_only: bool = False,
) -> list[asyncpg.Record]:
    return await repo.list_notifications(
        conn, user_id, unread_only, MODERATION_NOTIFICATIONS_PAGE_LIMIT
    )


async def mark_notification_read(
    conn: asyncpg.Connection,
    user_id: UUID,
    notification_id: UUID,
) -> None:
    marked = await repo.mark_notification_read(conn, user_id, notification_id)
    if not marked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )


async def mark_all_notifications_read(
    conn: asyncpg.Connection,
    user_id: UUID,
) -> None:
    await repo.mark_all_notifications_read(conn, user_id)
