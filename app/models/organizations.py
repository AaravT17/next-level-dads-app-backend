from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime
from typing import Literal


class OrganizationApplicationCreate(BaseModel):
    name: str = Field(max_length=200)
    email: EmailStr
    phone: str | None = None
    city: str
    province: str
    website: str | None = None
    description: str
    contact_name: str
    contact_title: str | None = None
    contact_email: EmailStr
    contact_phone: str | None = None
    application_answers: dict[str, str] = {}

class OrganizationApplicationResponse(BaseModel):
    id: UUID
    admin_user_id: UUID
    name: str
    email: EmailStr
    phone: str | None
    city: str
    province: str
    website: str | None
    description: str
    contact_name: str
    contact_title: str | None
    contact_email: EmailStr
    contact_phone: str | None
    status: Literal['pending', 'approved', 'rejected']
    application_answers: dict[str, str]
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None

class OrganizationAdminApplicationResponse(
    OrganizationApplicationResponse
):
    notes: list[InternalNoteResponse]

class OrganizationSummaryResponse(BaseModel):
    id: UUID
    name: str
    status: Literal["pending", "approved", "rejected"]
    created_at: datetime
    updated_at: datetime

class OrganizationApplicationDecision(BaseModel):
    status: Literal['approved', 'rejected']

class InternalNoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)

class InternalNoteResponse(BaseModel):
    id: UUID
    submitted_by: UUID
    content: str
    submitted_at: datetime

class InternalNotePreviewResponse(BaseModel):
    """Condensed internal note included in application list responses."""
    submitted_by_name: str | None = None
    content: str
    submitted_at: datetime

# ── List Views ────────────────────────────────────────────────
class ActionItemResponse(BaseModel):
    """Summary of a pending organization application for the action-items list on admin/Overview."""
    id: UUID
    name: str
    status: Literal["pending", "approved", "rejected"]
    created_at: datetime

class ApplicationRowResponse(BaseModel):
    """Summary of an organization application for the applications list on admin/Organizations."""
    id: UUID
    name: str
    status: Literal['pending', 'rejected']
    city: str
    province: str
    contact_name: str
    created_at: datetime
    updated_at: datetime

    
class ActivePartnerResponse(BaseModel):
    """Summary of an approved organization for the active partners list on admin/Organizations."""
    id: UUID
    name: str
    city: str
    province: str
    contact_name: str
    approved_at: datetime
