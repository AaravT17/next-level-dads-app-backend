from datetime import datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field, field_validator

# ------------------------------------------------------------------
# Organization chats
# ------------------------------------------------------------------

class ChatResponse(BaseModel):
    """Organization chat returned to an authenticated organization representative."""
    id: UUID
    organization_id: UUID
    organization_name: str
    created_at: datetime
    updated_at: datetime


class OrganizationMessageResponse(BaseModel):
    id: UUID
    chat_id: UUID
    sender_id: UUID | None
    reply_to_id: UUID | None
    content: str
    subject: dict | None
    edited_at: datetime | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

# ------------------------------------------------------------------
# Organization messages
# ------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    """Request payload for sending a message in an organization chat."""
    content: str = Field(..., min_length=1, max_length=2000)
    reply_to_id: UUID | None = None

    # Optional metadata for future event/resource message integration.
    subject: dict[str, Any] | None = None

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, content: str) -> str:
        if not isinstance(content, str):
            return content
        stripped_content = content.strip()
        if not stripped_content:
            raise ValueError("Message content cannot be empty")

        return stripped_content

class MessageResponse(BaseModel):
    """Organization chat message returned with optional sender display information."""
    id: UUID
    chat_id: UUID

    # Nullable because the database uses ON DELETE SET NULL.
    sender_id: UUID | None = None

    # These are not stored directly in organization_messages.
    # They can be populated later through a joined query.
    sender_name: str | None = None
    sender_avatar_url: str | None = None

    content: str
    subject: dict[str, Any] | None = None
    edited_at: datetime | None = None
    is_deleted: bool
    created_at: datetime

# TODO: Add reply-to request/response models after basic messaging works.
# Database schema already includes organization_messages.reply_to_id.

# ------------------------------------------------------------------
# Chat-list previews
# ------------------------------------------------------------------

class LastMessageResponse(BaseModel):
    """Condensed organization message included in chat-list previews."""
    id: UUID
    content: str
    sender_id: UUID | None = None
    sender_name: str | None = None
    subject: dict[str, Any] | None = None
    created_at: datetime
    is_deleted: bool


class ChatListItemResponse(BaseModel):
    """
    Organization chat summary for the admin chat list.

    Organization details are populated by joining organization_chats
    with organizations.
    """

    id: UUID
    organization_id: UUID
    organization_name: str
    updated_at: datetime
    last_message: LastMessageResponse | None = None
