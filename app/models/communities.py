from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from app.config.constants import (
    COMMUNITY_NAME_MAX_LENGTH,
    COMMUNITY_DESCRIPTION_MAX_LENGTH,
    CONVERSATION_TITLE_MIN_LENGTH,
    CONVERSATION_TITLE_MAX_LENGTH,
    CONVERSATION_BODY_MAX_LENGTH,
)
from typing import Literal


class CommunityResponse(BaseModel):
    id: UUID
    name: str = Field(max_length=COMMUNITY_NAME_MAX_LENGTH)
    description: str | None = Field(
        max_length=COMMUNITY_DESCRIPTION_MAX_LENGTH, default=None
    )
    member_count: int = Field(ge=0, default=0)
    created_by: UUID | None = None
    created_at: datetime
    is_member: bool = False
    role: Literal["admin", "member"] | None = None


class AuthorInfo(BaseModel):
    id: UUID
    name: str
    avatar_url: str | None = None
    about: str | None = None


class ConversationCreate(BaseModel):
    title: str = Field(
        min_length=CONVERSATION_TITLE_MIN_LENGTH,
        max_length=CONVERSATION_TITLE_MAX_LENGTH,
    )
    body: str = Field(min_length=1, max_length=CONVERSATION_BODY_MAX_LENGTH)
    prompt_type: str | None = None


class ConversationResponse(BaseModel):
    id: UUID
    community_id: UUID
    author: AuthorInfo | None = None
    title: str
    body: str
    prompt_type: str | None = None
    reply_count: int = 0
    heart_count: int = 0
    participant_count: int = 0
    is_hearted: bool = False
    is_deleted: bool = False
    has_pending_report: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=CONVERSATION_BODY_MAX_LENGTH)


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    author: AuthorInfo | None = None
    body: str
    reply_count: int = 0
    heart_count: int = 0
    is_hearted: bool = False
    is_deleted: bool = False
    has_pending_report: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ReplyCreate(BaseModel):
    body: str = Field(min_length=1, max_length=CONVERSATION_BODY_MAX_LENGTH)


class ReplyResponse(BaseModel):
    id: UUID
    message_id: UUID
    author: AuthorInfo | None = None
    body: str
    heart_count: int = 0
    is_hearted: bool = False
    is_deleted: bool = False
    has_pending_report: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ParticipantResponse(BaseModel):
    id: UUID
    name: str
    avatar_url: str | None = None
    first_joined_at: datetime
    last_active_at: datetime
