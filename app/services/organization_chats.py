import asyncpg
from datetime import datetime
from uuid import UUID
from fastapi import status, HTTPException
from app.models.organization_chats import (ChatResponse, SendMessageRequest, MessageResponse, LastMessageResponse, ChatListItemResponse)

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

async def get_organization_chat(
    conn: asyncpg.Connection,
    organization_id: UUID,
) -> ChatResponse:
    """
    Retrieve the existing chat associated with an organization.
    """

    row = await conn.fetchrow(
        """
        SELECT id, organization_id, created_at, updated_at
        FROM organization_chats
        WHERE organization_id = $1
        """,
        organization_id,
    )

    # if missing → error
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Organization chat not found.',
        )

    return ChatResponse(**dict(row))

 # TODO 2: Finish creating chat access auth function.
# async def verify_chat_access(

# admin can access any chat
# rep can only access their own org's chat  

# TODO 3: Finish get message history service function.
# async def get_messages()

# TODO 4: Finish send message service function.
# async def send_message()
# Verify the chat exists.
# Verify the current user can access that organization’s chat.
# Validate reply_to_id, if supplied, belongs to the same chat.
# Insert the message using the authenticated user as sender_id.
# Return the inserted row.

# TODO 5: Finish admin list all chats service function.
# async def list_chats()

# TODO: Add reply-to support with validation.

# TODO: Add message editing support.
# Validate that the authenticated sender owns the message,
# update content, and set edited_at.

# TODO: Add soft-delete support for messages.
# Validate that the authenticated sender owns the message,
# mark is_deleted = true, and preserve the database record.

# TODO: add a fallback of deleted user for null sender_id after an auth.user.id account is deleted