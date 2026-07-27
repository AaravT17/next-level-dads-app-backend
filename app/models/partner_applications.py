from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime
from typing import Literal


class PartnerApplicationCreate(BaseModel):
    name: str = Field(max_length=200)
    type: str | None = None
    email: EmailStr
    phone: str | None = None
    city: str
    province: str
    website: str | None = None
    description: str


class PartnerApplicationResponse(BaseModel):
    id: UUID
    name: str
    type: str | None
    email: str
    phone: str | None
    city: str
    province: str
    website: str | None
    description: str
    app_status: Literal['pending', 'approved', 'rejected']
    created_at: datetime
    updated_at: datetime | None
    accepted_at: datetime | None
    main_org_rep: UUID


class PartnerApplicationDecision(BaseModel):
    app_status: Literal['approved', 'rejected']
