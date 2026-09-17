import json
import logging
from datetime import datetime
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.common.config.constants import (
    COMMUNITY_ACTIVITY_COOLDOWN_HOURS,
    NOTIFICATION_RETENTION_DAYS,
    NOTIFICATIONS_PAGE_LIMIT,
)
from app.modules.notifications.models import NotificationResponse, NotificationCountResponse, NotificationType

logger = logging.getLogger(__name__)


UPSERT_COMMUNITY_ACTIVITY_DIGEST_SQL = """
        INSERT INTO notifications (user_id, type, payload, group_key)
        SELECT
            cm.user_id,
            'community_activity',
            jsonb_build_object(
                'community_id', c.id::text,
                'community_name', c.name,
                'community_image_url', c.image_url,
                'count', 1,
                '_since', GREATEST(
                    COALESCE(cm.last_visited_at, cm.joined_at),
                    COALESCE(uns.last_cleared_at, '-infinity'::timestamptz)
                ),
                '_visited', COALESCE(cm.last_visited_at, cm.joined_at)
            ),
            'community:' || c.id::text
        FROM community_members cm
        JOIN communities c ON c.id = cm.community_id
        LEFT JOIN user_notification_state uns ON uns.user_id = cm.user_id
        WHERE cm.community_id = $1
          AND cm.user_id <> $2
        ON CONFLICT (user_id, group_key) WHERE group_key IS NOT NULL
        DO UPDATE SET
            payload = CASE
                WHEN notifications.created_at < (EXCLUDED.payload->>'_since')::timestamptz
                    THEN EXCLUDED.payload
                ELSE jsonb_set(
                    notifications.payload,
                    '{count}',
                    to_jsonb(COALESCE((notifications.payload->>'count')::int, 0) + 1)
                )
            END,
            created_at = NOW(),
            updated_at = NOW()
        WHERE notifications.created_at >= (EXCLUDED.payload->>'_since')::timestamptz
           OR NOW() - (EXCLUDED.payload->>'_visited')::timestamptz
              >= make_interval(hours => $3)
        RETURNING user_id, (payload->>'count')::int AS count
        """


async def get_notifications(
    conn: asyncpg.Connection,
    user_id: str,
    cursor_created_at: datetime | None,
    cursor_id: UUID | None,
) -> list[NotificationResponse]:
    try:
        query, params = _build_get_notifications_query(
            user_id=UUID(user_id),
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
        )
        rows = await conn.fetch(query, *params)
        return [
            NotificationResponse(
                id=r['id'],
                type=r['type'],
                payload=json.loads(r['payload']),
                created_at=r['created_at'],
            )
            for r in rows
        ]
    except Exception:
        logger.exception('Failed to fetch notifications for user %s', user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch notifications. Please try again later.',
        )


async def get_unread_count(conn: asyncpg.Connection, user_id: str) -> NotificationCountResponse:
    try:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS count
            FROM notifications n
            LEFT JOIN user_notification_state uns ON uns.user_id = n.user_id
            WHERE n.user_id = $1
              AND n.created_at > GREATEST(
                  COALESCE(uns.last_read_at, '-infinity'),
                  COALESCE(uns.last_cleared_at, '-infinity'),
                  NOW() - make_interval(days => $2)
              )
            """,
            UUID(user_id),
            NOTIFICATION_RETENTION_DAYS,
        )
        return NotificationCountResponse(count=row['count'] if row else 0)
    except Exception:
        logger.exception('Failed to fetch unread notification count for user %s', user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch unread notification count. Please try again later.',
        )


async def create_notification(
    conn: asyncpg.Connection,
    user_id: UUID,
    notification_type: NotificationType,
    payload: dict,
) -> NotificationResponse | None:
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO notifications (user_id, type, payload)
            VALUES ($1, $2, $3)
            RETURNING id, type, payload, created_at
            """,
            user_id,
            notification_type,
            json.dumps(payload),
        )
        return NotificationResponse(
            id=row['id'],
            type=row['type'],
            payload=json.loads(row['payload']),
            created_at=row['created_at'],
        )
    except Exception:
        logger.exception('Failed to create notification for user %s', user_id)
        return None


async def create_notifications_bulk(
    conn: asyncpg.Connection,
    notifications: list[tuple[UUID, NotificationType, dict]],
) -> dict[UUID, NotificationResponse] | None:
    try:
        rows = await conn.fetch(
            """
            INSERT INTO notifications (user_id, type, payload)
            SELECT * FROM unnest($1::uuid[], $2::text[], $3::jsonb[])
            RETURNING user_id, id, type, payload, created_at
            """,
            [n[0] for n in notifications],
            [n[1] for n in notifications],
            [json.dumps(n[2]) for n in notifications],
        )
        return {
            r['user_id']: NotificationResponse(
                id=r['id'],
                type=r['type'],
                payload=json.loads(r['payload']),
                created_at=r['created_at'],
            )
            for r in rows
        }
    except Exception:
        logger.exception('Failed to create notifications for users %s', [str(n[0]) for n in notifications])
        return None


async def upsert_community_activity_digests(
    conn: asyncpg.Connection,
    community_id: UUID,
    author_id: UUID,
) -> list[UUID]:
    """Raise or bump the community-activity digest for every member who should see it.

    Returns the ids of members whose digest was *opened* by this call, which is
    not the same as everyone whose count changed -- see the WS note below.

    One statement, one round trip, whatever the community's size. The partial
    unique index on (user_id, group_key) is what makes that possible: opening a
    digest and adding to one are the same INSERT. The alternative -- a row per
    member per post -- is what this whole design exists to avoid.

    Three outcomes per member, decided in SQL because the decision needs the
    member's own visit watermark:

      * no digest yet            -> open one at a count of 1
      * digest raised since their last visit -> still unseen, so add to it
      * digest predates their last visit     -> they have been and looked; stay
                                                silent until the cooldown has run

    Two watermarks ride along in the proposed payload, because ON CONFLICT can
    see only the proposed row and the existing one -- never the rows the SELECT
    read them from:

      * `_since`   the later of "opened this community" and "cleared the
                   notification centre". Either means the member has drawn a
                   line under what they have seen, so a digest older than it
                   restarts at one rather than carrying its old count forward.
      * `_visited` the community visit alone, which is what the cooldown keys
                   off. Clearing the centre is not the same as catching up on a
                   community and must not buy six hours of silence.
    """
    rows = await conn.fetch(
        UPSERT_COMMUNITY_ACTIVITY_DIGEST_SQL,
        community_id,
        author_id,
        COMMUNITY_ACTIVITY_COOLDOWN_HOURS,
    )
    # Only a freshly opened digest is worth a socket event. Publishing on every
    # increment would put one Redis PUBLISH per member on every post and light
    # the bell up repeatedly for something the member has already been told
    # about; the climbing count rides along on the next fetch instead.
    return [r['user_id'] for r in rows if r['count'] == 1]


async def mark_read(conn: asyncpg.Connection, user_id: str) -> datetime:
    now = await conn.fetchval(
        """
        INSERT INTO user_notification_state (user_id, last_read_at)
        VALUES ($1, NOW())
        ON CONFLICT (user_id)
        DO UPDATE SET last_read_at = GREATEST(COALESCE(user_notification_state.last_read_at, NOW()), NOW())
        RETURNING last_read_at
        """,
        UUID(user_id),
    )
    return now


async def clear_all(conn: asyncpg.Connection, user_id: str) -> tuple[datetime, datetime]:
    row = await conn.fetchrow(
        """
        INSERT INTO user_notification_state (user_id, last_read_at, last_cleared_at)
        VALUES ($1, NOW(), NOW())
        ON CONFLICT (user_id)
        DO UPDATE SET
            last_read_at = GREATEST(COALESCE(user_notification_state.last_read_at, NOW()), NOW()),
            last_cleared_at = GREATEST(COALESCE(user_notification_state.last_cleared_at, NOW()), NOW())
        RETURNING last_read_at, last_cleared_at
        """,
        UUID(user_id),
    )
    return row['last_read_at'], row['last_cleared_at']


def _build_get_notifications_query(
    user_id: UUID,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> tuple[str, list]:
    params: list = [user_id, NOTIFICATION_RETENTION_DAYS]
    i = 3

    cursor_clause = ''
    if cursor_created_at and cursor_id:
        cursor_clause = f'AND (n.created_at, n.id) < (${i}, ${i + 1})'
        params.extend([cursor_created_at, cursor_id])
        i += 2

    query = f"""
        SELECT n.id, n.type, n.payload, n.created_at
        FROM notifications n
        LEFT JOIN user_notification_state uns ON uns.user_id = n.user_id
        WHERE n.user_id = $1
          AND n.created_at > GREATEST(COALESCE(uns.last_cleared_at, '-infinity'), NOW() - make_interval(days => $2))
          {cursor_clause}
        ORDER BY n.created_at DESC, n.id DESC
        LIMIT ${i}
    """
    params.append(NOTIFICATIONS_PAGE_LIMIT)

    return query, params
