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
    admin_user_id: UUID | None
    name: str
    email: str
    phone: str | None
    city: str
    province: str
    website: str | None
    description: str
    contact_name: str
    contact_title: str | None
    contact_email: str
    contact_phone: str | None
    status: Literal['pending', 'approved', 'rejected']
    application_answers: dict[str, str]
    notes: list[dict] | None
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
