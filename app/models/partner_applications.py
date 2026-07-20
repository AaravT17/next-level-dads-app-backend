from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime
from typing import Literal


class PartnerApplicationCreate(BaseModel):
    organization_name: str = Field(max_length=200)
    organization_type: str
    region: str
    website: str | None = None
    mission: str
    representative_name: str
    representative_title: str | None = None
    representative_email: EmailStr
    representative_phone: str | None = None
    primary_goals: str
    partnership_reason: str
    estimated_reach: str | None = None


class PartnerApplicationResponse(BaseModel):
    id: UUID
    organization_name: str
    organization_type: str
    region: str
    website: str | None
    mission: str
    representative_name: str
    representative_title: str | None
    representative_email: str
    representative_phone: str | None
    primary_goals: str
    partnership_reason: str
    estimated_reach: str | None
    status: Literal['pending', 'needs_changes', 'approved', 'denied']
    decision_message: str | None
    submitted_at: datetime


class PartnerApplicationDecision(BaseModel):
    status: Literal['approved', 'denied', 'needs_changes']
    decision_message: str
    admin_notes: str | None = None