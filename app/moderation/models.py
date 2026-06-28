from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.config.constants import MODERATION_REPORT_REASON_MAX_LENGTH


class ContentType(str, Enum):
    """A piece of user content the moderation service can act on."""

    CONVERSATION = "conversation"
    MESSAGE = "message"
    REPLY = "reply"


class ModerationLayer(str, Enum):
    """Which layer flagged the content (also used as the audit `layer`)."""

    PROFANITY = "profanity"
    HATE_SPEECH = "hate_speech"
    REPORT = "report"


class NotificationType(str, Enum):
    """Kind of moderation notification shown to a user."""

    CONTENT_REMOVED = "content_removed"
    TEMPORARY_BAN = "temporary_ban"


@dataclass(frozen=True)
class ModerationResult:
    """Outcome of running a single moderation layer over some text."""

    flagged: bool
    layer: ModerationLayer | None = None
    reason: str | None = None
    score: float | None = None

    @classmethod
    def clean(cls) -> "ModerationResult":
        return cls(flagged=False)


# ── Reporting API schemas ──────────────────────────────────────────────────


class ReportCreate(BaseModel):
    content_type: ContentType
    content_id: UUID
    reason: str | None = Field(
        default=None, max_length=MODERATION_REPORT_REASON_MAX_LENGTH
    )


class ReportResponse(BaseModel):
    id: UUID
    content_type: ContentType
    content_id: UUID
    status: str
    created_at: datetime


# ── Notification API schemas ───────────────────────────────────────────────


class NotificationResponse(BaseModel):
    id: UUID
    type: NotificationType
    content_type: ContentType | None = None
    content_id: UUID | None = None
    reason: str | None = None
    message: str
    is_read: bool
    created_at: datetime


class BanStatusResponse(BaseModel):
    banned: bool
    expires_at: datetime | None = None


# ── User-report API schemas ────────────────────────────────────────────────


class UserReportCreate(BaseModel):
    reported_id: UUID
    reason: str | None = Field(
        default=None, max_length=MODERATION_REPORT_REASON_MAX_LENGTH
    )


class UserReportResponse(BaseModel):
    id: UUID
    reported_id: UUID
    status: str
    created_at: datetime


# ── Admin API schemas ──────────────────────────────────────────────────────


class AdminContentReportItem(BaseModel):
    id: UUID
    content_type: ContentType
    content_id: UUID
    reporter_id: UUID
    reporter_name: str | None = None
    reason: str | None = None
    status: str
    created_at: datetime


class AdminUserReportItem(BaseModel):
    id: UUID
    reported_id: UUID
    reported_name: str | None = None
    reporter_id: UUID
    reporter_name: str | None = None
    reason: str | None = None
    status: str
    created_at: datetime


class AdminFilteredMessageItem(BaseModel):
    id: UUID
    content_type: ContentType
    content_id: UUID
    author_id: UUID | None = None
    author_name: str | None = None
    community_id: UUID | None = None
    original_text: str
    layer: ModerationLayer
    reason: str | None = None
    score: float | None = None
    created_at: datetime


class AdminBanItem(BaseModel):
    id: UUID
    user_id: UUID
    user_name: str | None = None
    reason: str
    created_at: datetime
    expires_at: datetime


class AdminBanCreate(BaseModel):
    user_id: UUID
    reason: str
    duration_hours: int = Field(ge=1, le=8760)


class AdminReportStatusUpdate(BaseModel):
    status: str = Field(pattern="^(reviewed|dismissed|actioned)$")
