import logging
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies.auth import get_admin_user
from app.dependencies.db import get_db
from app.moderation.models import (
    AdminBanCreate,
    AdminBanItem,
    AdminContentReportItem,
    AdminFilteredMessageItem,
    AdminReportStatusUpdate,
    AdminUserReportItem,
    ContentType,
    ModerationLayer,
    NotificationType,
)
from app.moderation.messages import build_ban_message, build_moderator_removal_message
from app.moderation.repository import (
    get_content_context_admin,
    get_content_for_moderator_action,
    get_content_report_for_action,
    get_user_activity_context_admin,
    get_user_report_for_action,
    filtered_message_exists,
    deactivate_active_bans,
    insert_ban,
    insert_filtered_message,
    insert_notification,
    lift_ban,
    list_active_bans_admin,
    list_content_reports,
    list_filtered_messages_admin,
    list_user_reports,
    soft_delete_content,
    update_content_report_status,
    update_user_report_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
)

_DEFAULT_LIMIT = 50
_DEFAULT_OFFSET = 0
_ADMIN_USER_BAN_HOURS = 24 * 7


# ── Content reports ────────────────────────────────────────────────────────


@router.get("/reports/content", response_model=list[AdminContentReportItem])
async def get_content_reports(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=200),
    offset: int = Query(_DEFAULT_OFFSET, ge=0),
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        records = await list_content_reports(conn, status_filter, limit, offset)
        return [AdminContentReportItem(**dict(r)) for r in records]
    except Exception:
        logger.exception("Failed to fetch content reports")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch content reports.",
        )


@router.patch(
    "/reports/content/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_content_report(
    report_id: UUID,
    payload: AdminReportStatusUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        async with conn.transaction():
            # Lock the report row and capture its prior status so the removal
            # side effects below run only on the first transition to actioned.
            report = await get_content_report_for_action(conn, report_id)
            if report is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Report not found."
                )
            already_actioned = report["status"] == "actioned"
            await update_content_report_status(conn, report_id, payload.status)
            if payload.status == "actioned" and not already_actioned:
                content_type = ContentType(report["content_type"])
                content = await get_content_for_moderator_action(
                    conn,
                    content_type,
                    report["content_id"],
                )
                if content is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Reported content not found.",
                    )

                await soft_delete_content(
                    conn,
                    content_type,
                    report["content_id"],
                    deleted_by_moderator=True,
                )
                if not await filtered_message_exists(
                    conn,
                    content_type,
                    report["content_id"],
                    ModerationLayer.REPORT,
                ):
                    await insert_filtered_message(
                        conn,
                        content_type,
                        report["content_id"],
                        content["author_id"],
                        content["community_id"],
                        content["original_text"],
                        ModerationLayer.REPORT,
                        report["reason"],
                        None,
                    )
                if content["author_id"] is not None:
                    await insert_notification(
                        conn,
                        content["author_id"],
                        NotificationType.CONTENT_REMOVED,
                        build_moderator_removal_message(content_type),
                        content_type=content_type,
                        content_id=report["content_id"],
                        layer=ModerationLayer.REPORT,
                        reason=report["reason"],
                    )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to action content report %s", report_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update report.",
        )


# ── User reports ───────────────────────────────────────────────────────────


@router.get("/reports/users", response_model=list[AdminUserReportItem])
async def get_user_reports(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=200),
    offset: int = Query(_DEFAULT_OFFSET, ge=0),
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        records = await list_user_reports(conn, status_filter, limit, offset)
        return [AdminUserReportItem(**dict(r)) for r in records]
    except Exception:
        logger.exception("Failed to fetch user reports")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user reports.",
        )


@router.patch(
    "/reports/users/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_user_report(
    report_id: UUID,
    payload: AdminReportStatusUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        async with conn.transaction():
            # Lock the report row and capture its prior status so the ban side
            # effects below run only on the first transition to actioned.
            report = await get_user_report_for_action(conn, report_id)
            if report is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Report not found."
                )
            already_actioned = report["status"] == "actioned"
            await update_user_report_status(conn, report_id, payload.status)
            if payload.status == "actioned" and not already_actioned:
                reason = report["reason"] or "Confirmed user report"
                # TODO: Remove or moderator-hide the reported user's content
                # when applying an admin-confirmed ban.
                await insert_ban(
                    conn,
                    report["reported_id"],
                    reason,
                    _ADMIN_USER_BAN_HOURS,
                )
                await insert_notification(
                    conn,
                    report["reported_id"],
                    NotificationType.TEMPORARY_BAN,
                    build_ban_message(_ADMIN_USER_BAN_HOURS),
                )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to action user report %s", report_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update report.",
        )


# ── Filtered messages ──────────────────────────────────────────────────────


@router.get("/filtered-messages", response_model=list[AdminFilteredMessageItem])
async def get_filtered_messages(
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=200),
    offset: int = Query(_DEFAULT_OFFSET, ge=0),
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        records = await list_filtered_messages_admin(conn, limit, offset)
        return [AdminFilteredMessageItem(**dict(r)) for r in records]
    except Exception:
        logger.exception("Failed to fetch filtered messages")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch filtered messages.",
        )


# ── Review context ─────────────────────────────────────────────────────────


@router.get("/context/content/{content_type}/{content_id}")
async def get_content_context(
    content_type: str,
    content_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    if content_type not in {"conversation", "message", "reply"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid content type.",
        )
    try:
        context = await get_content_context_admin(conn, content_type, content_id)
        if context is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Content not found."
            )
        return context
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Failed to fetch content context for %s %s", content_type, content_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch content context.",
        )


@router.get("/context/users/{user_id}")
async def get_user_context(
    user_id: UUID,
    limit: int = Query(200, ge=1, le=500),
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        context = await get_user_activity_context_admin(conn, user_id, limit)
        if context is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
            )
        return context
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to fetch user context for %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user context.",
        )


# ── Bans ───────────────────────────────────────────────────────────────────


@router.get("/bans", response_model=list[AdminBanItem])
async def get_active_bans(
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=200),
    offset: int = Query(_DEFAULT_OFFSET, ge=0),
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        records = await list_active_bans_admin(conn, limit, offset)
        return [AdminBanItem(**dict(r)) for r in records]
    except Exception:
        logger.exception("Failed to fetch bans")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch bans.",
        )


@router.post("/bans", response_model=AdminBanItem, status_code=status.HTTP_201_CREATED)
async def create_ban(
    payload: AdminBanCreate,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        async with conn.transaction():
            # Replace any existing active ban so a user never accumulates
            # overlapping bans (which would survive an admin lifting one).
            await deactivate_active_bans(conn, payload.user_id)
            record = await insert_ban(
                conn,
                payload.user_id,
                payload.reason,
                payload.duration_hours,
            )
        user_name = await conn.fetchval(
            "SELECT name FROM public.users WHERE id = $1", payload.user_id
        )
        return AdminBanItem(
            id=record["id"],
            user_id=payload.user_id,
            user_name=user_name,
            reason=payload.reason,
            created_at=record["created_at"],
            expires_at=record["expires_at"],
        )
    except Exception:
        logger.exception("Failed to create ban for user %s", payload.user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create ban.",
        )


@router.delete("/bans/{ban_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_ban(
    ban_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        lifted = await lift_ban(conn, ban_id)
        if not lifted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Ban not found."
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to lift ban %s", ban_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to lift ban.",
        )
