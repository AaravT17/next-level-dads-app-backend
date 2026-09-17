from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime
from app.common.config.constants import (
    COMMUNITY_NAME_MAX_LENGTH,
    COMMUNITY_DESCRIPTION_MAX_LENGTH,
    COMMUNITY_INVITE_MAX_RECIPIENTS,
    CONVERSATION_TITLE_MIN_LENGTH,
    CONVERSATION_TITLE_MAX_LENGTH,
    CONVERSATION_BODY_MAX_LENGTH,
    CONVERSATION_PROMPT_TYPES,
)
from typing import Literal
from app.modules.users.models import UserBase


# TODO: Contains fields not required/used by the frontend, can be trimmed
class CommunityMemberResponse(UserBase):
    created_at: datetime
    joined_at: datetime
    role: Literal['admin', 'member'] = Field(default='member')


class CommunityResponse(BaseModel):
    id: UUID
    name: str = Field(max_length=COMMUNITY_NAME_MAX_LENGTH)
    description: str | None = Field(
        max_length=COMMUNITY_DESCRIPTION_MAX_LENGTH, default=None
    )
    image_url: str | None = None
    member_count: int = Field(ge=0, default=0)
    created_by: UUID | None = None
    created_at: datetime
    is_member: bool = False
    role: Literal['admin', 'member'] | None = None
    # Conversations with activity since the caller last opened this community.
    # Only "my communities" computes it; discover and single-community reads return
    # 0, since a non-member has no watermark and nothing to come back to.
    # Saturates at NEW_ACTIVITY_CAP -- the UI renders 99+ past that anyway.
    new_activity_count: int = Field(ge=0, default=0)


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

    @field_validator('prompt_type')
    @classmethod
    def validate_prompt_type(cls, v: str | None) -> str | None:
        """One of a fixed set, or nothing at all.

        The client offers these as a picker, so anything else arrived by hand.
        Closing the field is what makes the chip worth reading: a reader
        scanning a community should be able to trust that every post marked
        "question" means the same thing.

        An empty string is not a sixth kind -- a picker left on its default
        sends one, and it should mean the same as omitting the field.
        """
        if v is None:
            return None
        v = v.strip().lower()
        if not v:
            return None
        if v not in CONVERSATION_PROMPT_TYPES:
            raise ValueError('Invalid conversation type.')
        return v


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


class FeedConversationResponse(ConversationResponse):
    community_name: str


# Why a conversation appears in "get back into it". Ordered by precedence:
# authoring a thread is a stronger stake than replying, which is stronger than
# hearting. The client renders these verbatim, so the set is closed.
ResumeReason = Literal['authored', 'replied', 'hearted']


class ResumeConversationResponse(FeedConversationResponse):
    reason: ResumeReason
    # Replies added by other people since the caller last acted on the thread.
    # Zero is meaningful: the card then shows the reason alone.
    unseen_reply_count: int


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


class CommunityInviteRequest(BaseModel):
    recipient_ids: list[UUID] = Field(
        ..., min_length=1, max_length=COMMUNITY_INVITE_MAX_RECIPIENTS
    )

    @field_validator("recipient_ids")
    def deduplicate_recipient_ids(cls, recipient_ids: list[UUID]) -> list[UUID]:
        # Selecting the same person twice is a client slip, not a request for
        # two invites.
        #
        # Runs after parsing so it dedupes UUID objects. In "before" mode it saw
        # raw strings, and two spellings of one id -- differing case, or braces --
        # survived as distinct entries and sent two invites into the same DM.
        #
        # The length cap therefore applies to what was sent, before deduping.
        # That is the safe direction: deduping can only reduce the count, so the
        # cap can never be inflated past COMMUNITY_INVITE_MAX_RECIPIENTS.
        return list(dict.fromkeys(recipient_ids))


class CommunityInviteResponse(BaseModel):
    invited_count: int = Field(ge=0)
