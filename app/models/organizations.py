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
    notes: list[dict]
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None


class OrganizationApplicationDecision(BaseModel):
    status: Literal['approved', 'rejected']
