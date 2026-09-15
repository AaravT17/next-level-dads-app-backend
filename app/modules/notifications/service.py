import json
import logging
from datetime import datetime
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.common.config.constants import NOTIFICATION_RETENTION_DAYS, NOTIFICATIONS_PAGE_LIMIT
from app.modules.notifications.models import NotificationResponse, NotificationCountResponse, NotificationType

logger = logging.getLogger(__name__)


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
) -> list[NotificationResponse] | None:
    try:
        rows = await conn.fetch(
            """
            INSERT INTO notifications (user_id, type, payload)
            SELECT * FROM unnest($1::uuid[], $2::text[], $3::jsonb[])
            RETURNING id, type, payload, created_at
            """,
            [n[0] for n in notifications],
            [n[1] for n in notifications],
            [json.dumps(n[2]) for n in notifications],
        )
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
        logger.exception('Failed to create notifications for users %s', [str(n[0]) for n in notifications])
        return None


async def mark_read(conn: asyncpg.Connection, user_id: str) -> datetime:
    now = await conn.fetchval(
        """
        INSERT INTO user_notification_state (user_id, last_read_at)
        VALUES ($1, NOW())
        ON CONFLICT (user_id)
        DO UPDATE SET last_read_at = NOW()
        RETURNING last_read_at
        """,
        UUID(user_id),
    )
    return now


async def clear_all(conn: asyncpg.Connection, user_id: str) -> datetime:
    now = await conn.fetchval(
        """
        INSERT INTO user_notification_state (user_id, last_read_at, last_cleared_at)
        VALUES ($1, NOW(), NOW())
        ON CONFLICT (user_id)
        DO UPDATE SET last_read_at = NOW(), last_cleared_at = NOW()
        RETURNING last_cleared_at
        """,
        UUID(user_id),
    )
    return now


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
