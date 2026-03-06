from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Literal
from decimal import Decimal
from app.config.constants import (
    EVENT_DESCRIPTION_MAX_LENGTH,
    EVENT_LOCATION_MAX_LENGTH,
    EVENT_NAME_MAX_LENGTH,
    EVENT_HOSTED_BY_ORG_NAME_MAX_LENGTH,
    EVENT_HOSTED_BY_CONTACT_EMAIL_MAX_LENGTH,
    EVENT_HOSTED_BY_CONTACT_PHONE_MAX_LENGTH,
)


class EventResponse(BaseModel):
    id: UUID
    name: str = Field(max_length=EVENT_NAME_MAX_LENGTH)
    description: str | None = Field(
        max_length=EVENT_DESCRIPTION_MAX_LENGTH, default=None
    )
    type: Literal["local", "virtual"]
    starts_at: datetime
    ends_at: datetime | None = None
    location: str = Field(max_length=EVENT_LOCATION_MAX_LENGTH)
    latitude: float | None = None
    longitude: float | None = None
    hosted_by_user_id: UUID | None = None
    hosted_by_org_name: str | None = Field(
        max_length=EVENT_HOSTED_BY_ORG_NAME_MAX_LENGTH,
        default=None,
    )
    hosted_by_community_id: UUID | None = None
    contact_email: str | None = Field(
        max_length=EVENT_HOSTED_BY_CONTACT_EMAIL_MAX_LENGTH,
        default=None,
    )
    contact_phone: str | None = Field(
        max_length=EVENT_HOSTED_BY_CONTACT_PHONE_MAX_LENGTH,
        default=None,
    )
    price_cad: Decimal = Field(ge=0, default=0)
    attendee_count: int = Field(ge=0, default=0)
    created_by: UUID | None = None
    created_at: datetime
    is_attending: bool = False
