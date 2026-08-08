import asyncpg
import json
from datetime import datetime
from uuid import UUID
from fastapi import status, HTTPException
from app.models.organization_chats import (ChatResponse, SendMessageRequest, MessageResponse, LastMessageResponse, ChatListItemResponse)
from app.utils.json_utils import parse_jsonb_value

async def create_organization_chat(
    conn: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    """
    Create the single organization chat associated with a newly created organization.
    This is intended to run during the organization application submission flow,
    after the organization and organization representative records are created.
    """

    await conn.execute(
        """
        INSERT INTO organization_chats (organization_id)
        VALUES ($1)
        """,
        organization_id,
    )

# ============================================================
# Shared Admin + Partner Messaging
# ============================================================

async def verify_chat_access(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
) -> None:
    """
    Verify that an authenticated user may access an organization chat.
    NLD admins may access any organization chat.
    Partner users may access only chats belonging to an organization they represent.
    """

    chat = await conn.fetchrow(
        """
        SELECT organization_id
        FROM organization_chats
        WHERE id = $1
        """,
        chat_id,
    )

    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization chat not found.",
        )

    # Verify that the user is an NLD admin.
    organization_id = chat["organization_id"]
    admin = await conn.fetchval(
        """
        SELECT is_admin
        FROM users
        WHERE id = $1
        """,
        user_id,
    )

    if admin:
        return

    # If not an admin, verify that the user is a representative of the organization associated with the chat.
    representative = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM organization_representatives
            WHERE user_id = $1
                AND organization_id = $2
        )
        """,
        user_id,
        organization_id,
    )

    if representative:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to this organization chat.",
    )

# TODO: If organizations support multiple representatives in the future, update get_sender_name() to return the representative's name from organization_representatives instead of organizations.contact_name.
async def get_sender_name(
    conn: asyncpg.Connection,
    sender_id: UUID,
) -> str | None:
    """
    Return the display name for an organization-message sender.
    NLD admin names come from public.users.
    Partner representative names come from organizations.contact_name.
    """

    return await conn.fetchval(
        """
        SELECT COALESCE(
            (
                SELECT u.name
                FROM public.users u
                WHERE u.id = $1
            ),
            (
                SELECT o.contact_name
                FROM organizations o
                WHERE o.admin_user_id = $1
            )
        )
        """,
        sender_id,
    )

async def get_messages(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    cursor_id: UUID | None = None,
    cursor_created_at: datetime | None = None,
) -> list[MessageResponse]:
    """
    Return messages from an organization chat after verifying that
    the authenticated user has access to the chat.
    """

    await verify_chat_access(
        conn=conn,
        user_id=user_id,
        chat_id=chat_id,
    )

    query = """
    SELECT
        m.id,
        m.chat_id,
        m.sender_id,
        COALESCE(u.name, o.contact_name) AS sender_name,
        m.content,
        m.subject,
        m.edited_at,
        m.is_deleted,
        m.created_at
    FROM organization_messages m
    LEFT JOIN public.users u
        ON u.id = m.sender_id
    LEFT JOIN organizations o
        ON o.admin_user_id = m.sender_id
    WHERE m.chat_id = $1
      AND (
          $2::timestamptz IS NULL
          OR m.created_at < $2
          OR (m.created_at = $2 AND m.id < $3)
      )
    ORDER BY m.created_at DESC, m.id DESC
    LIMIT 50
    """

    rows = await conn.fetch(
        query,
        chat_id,
        cursor_created_at,
        cursor_id,
    )

    messages: list[MessageResponse] = []

    for row in rows:
        row_data = dict(row)

        row_data["subject"] = parse_jsonb_value(
            row_data.get("subject"),
            None,
        )

        messages.append(
            MessageResponse(
                **row_data,
                sender_avatar_url=None,
            )
        )

    return messages
   

async def send_message(
    conn: asyncpg.Connection,
    user_id: UUID,
    chat_id: UUID,
    body: SendMessageRequest,

) -> MessageResponse:
    """
    Send a message in an organization chat after verifying access.
    """

    await verify_chat_access(
        conn=conn,
        user_id=user_id,
        chat_id=chat_id,
    )

    row = await conn.fetchrow(
        """
        INSERT INTO organization_messages (
            chat_id,
            sender_id,
            content,
            subject
        )
        VALUES ($1, $2, $3, $4)
        RETURNING
            id,
            chat_id,
            sender_id,
            content,
            subject,
            edited_at,
            is_deleted,
            created_at
        """,
        chat_id,
        user_id,
        body.content,
        json.dumps(body.subject) if body.subject is not None else None,
    )

    row_data = dict(row)
    row_data["subject"] = parse_jsonb_value(row_data.get("subject"), None)

    sender_name = await get_sender_name(
    conn=conn,
    sender_id=user_id,
    )

    return MessageResponse(
        **row_data,
        sender_name=sender_name,
        sender_avatar_url=None,
    )

# ============================================================
# Admin Messaging
# ============================================================
async def list_chats(
    conn: asyncpg.Connection,
    name: str | None = None,
    cursor_id: UUID | None = None,
    cursor_updated_at: datetime | None = None,
) -> list[ChatListItemResponse]:
    """
    Return organization chats for the admin messaging list.
    Each list item includes organization information and a preview
    of the most recent message, if one exists.
    """

    rows = await conn.fetch(
        """
        SELECT
            oc.id,
            oc.organization_id,
            o.name AS organization_name,
            oc.updated_at,
            lm.id AS last_message_id,
            lm.content AS last_message_content,
            lm.sender_id AS last_message_sender_id,
            lm.sender_name AS last_message_sender_name,
            lm.subject AS last_message_subject,
            lm.created_at AS last_message_created_at,
            lm.is_deleted AS last_message_is_deleted
        FROM organization_chats oc
        JOIN organizations o
            ON o.id = oc.organization_id
        LEFT JOIN LATERAL (
            SELECT
                m.id,
                m.content,
                m.sender_id,
                COALESCE(u.name, sender_org.contact_name) AS sender_name,
                m.subject,
                m.created_at,
                m.is_deleted
            FROM organization_messages m
            LEFT JOIN public.users u
                ON u.id = m.sender_id
            LEFT JOIN organizations sender_org
                ON sender_org.admin_user_id = m.sender_id
            WHERE m.chat_id = oc.id
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT 1
        ) lm ON TRUE
        WHERE
            ($1::text IS NULL OR o.name ILIKE '%' || $1 || '%')
            AND (
                $2::timestamptz IS NULL
                OR oc.updated_at < $2
                OR (oc.updated_at = $2 AND oc.id < $3)
            )
        ORDER BY oc.updated_at DESC, oc.id DESC
        LIMIT 50
        """,
        name,
        cursor_updated_at,
        cursor_id,
    )

    chats: list[ChatListItemResponse] = []

    for row in rows:
        last_message = None

        if row["last_message_id"] is not None:
            last_message_subject = parse_jsonb_value(
                row["last_message_subject"],
                None,
            ) 

            last_message = LastMessageResponse(
                id=row["last_message_id"],
                content=row["last_message_content"],
                sender_id=row["last_message_sender_id"],
                sender_name=row['last_message_sender_name'],
                subject=last_message_subject,
                created_at=row["last_message_created_at"],
                is_deleted=row["last_message_is_deleted"],
            )

        chats.append(
            ChatListItemResponse(
                id=row["id"],
                organization_id=row["organization_id"],
                organization_name=row["organization_name"],
                updated_at=row["updated_at"],
                last_message=last_message,
            )
        )

    return chats

async def get_organization_chat(
    conn: asyncpg.Connection,
    chat_id: UUID,
) -> ChatResponse:
    """
    Retrieve the existing chat associated with an organization.
    """
    row = await conn.fetchrow(
        """
        SELECT
            oc.id,
            oc.organization_id,
            o.name AS organization_name,
            oc.created_at,
            oc.updated_at
        FROM organization_chats oc
        JOIN organizations o
            ON o.id = oc.organization_id
        WHERE oc.id = $1
        """,
        chat_id,
    )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Organization chat not found.',
        )

    return ChatResponse(**dict(row))


#async def create_or_get_organization_chat()
# Verify the organization exists.
# Verify the requester is allowed to access it.
# Find an existing chat by organization_id.
# Return it if found.
# Otherwise insert and return a new chat.

#async def create_organization_message()
# Verify the chat exists.
# Verify the current user can access that organization’s chat.
# Validate reply_to_id, if supplied, belongs to the same chat.
# Insert the message using the authenticated user as sender_id.
# Return the inserted row.

#async def verify_organization_chat_access()
# admin can access any chat
# rep can only access their own org's chat    


#async def create_or_get_organization_chat()
# Verify the organization exists.
# Verify the requester is allowed to access it.
# Find an existing chat by organization_id.
# Return it if found.
# Otherwise insert and return a new chat.

#async def create_organization_message()
# Verify the chat exists.
# Verify the current user can access that organization’s chat.
# Validate reply_to_id, if supplied, belongs to the same chat.
# Insert the message using the authenticated user as sender_id.
# Return the inserted row.

#async def verify_organization_chat_access()
# admin can access any chat
# rep can only access their own org's chat    

# TODO: Add reply-to support with validation.

# TODO: Add message editing support.
# Validate that the authenticated sender owns the message,
# update content, and set edited_at.

# TODO: Add soft-delete support for messages.
# Validate that the authenticated sender owns the message,
# mark is_deleted = true, and preserve the database record.

# TODO: add a fallback of deleted user for null sender_id after an auth.user.id account is deleted

# TODO: Validate that cursor_created_at and cursor_id are supplied together before applying pagination.

# TODO: Add project-consistent database error handling
