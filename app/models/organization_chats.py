from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class OrganizationChatResponse(BaseModel):
    id: UUID
    organization_id: UUID
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
