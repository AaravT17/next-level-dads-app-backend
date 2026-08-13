from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Literal
from decimal import Decimal
from app.config.constants import (
    EVENT_DESCRIPTION_MAX_LENGTH,
    EVENT_LOCATION_MAX_LENGTH,
    EVENT_NAME_MAX_LENGTH,
    EVENT_HOSTED_BY_CONTACT_EMAIL_MAX_LENGTH,
    EVENT_HOSTED_BY_CONTACT_PHONE_MAX_LENGTH,
)

class Event(BaseModel):
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
    hosted_by_org_id: UUID | None
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
    hosted_by_org_id: UUID | None
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

# Model for new event creations
class EventCreate(BaseModel):
    name: str = Field(max_length=EVENT_NAME_MAX_LENGTH)
    description: str | None = Field(max_length=EVENT_DESCRIPTION_MAX_LENGTH, default=None)
    type: Literal["local", "virtual"]
    starts_at: datetime
    ends_at: datetime | None = Field(default=None)
    location: str = Field(max_length=EVENT_LOCATION_MAX_LENGTH)
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)
    contact_email: str | None = Field(max_length=EVENT_HOSTED_BY_CONTACT_EMAIL_MAX_LENGTH, default=None)
    contact_phone: str | None = Field(max_length=EVENT_HOSTED_BY_CONTACT_PHONE_MAX_LENGTH, default=None)
    price_cad: Decimal

# Return when new event is successfully created
class EventCreateResponse(BaseModel):
    id: UUID

# Model for event updates
class EventUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    type: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location: str | None = None
    latitude: float | None = None 
    longitude: float | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    price_cad: Decimal | None = None

class EventUpdateResponse(BaseModel):
    id: UUID
    name: str = Field(max_length=EVENT_NAME_MAX_LENGTH)
    description: str | None = Field(max_length=EVENT_DESCRIPTION_MAX_LENGTH)
    type: Literal["local", "virtual"]
    starts_at: datetime
    ends_at: datetime | None
    location: str = Field(max_length=EVENT_LOCATION_MAX_LENGTH)
    latitude: float | None
    longitude: float | None
    contact_email: str | None = Field(max_length=EVENT_HOSTED_BY_CONTACT_EMAIL_MAX_LENGTH)
    contact_phone: str | None = Field(max_length=EVENT_HOSTED_BY_CONTACT_PHONE_MAX_LENGTH)
    price_cad: Decimal
    created_at: datetime
    app_status: Literal["pending", "approved", "rejected"]


# Response for events on the partner portal
class PartnerEventResponse(BaseModel):
    id: UUID
    name: str = Field(max_length=EVENT_NAME_MAX_LENGTH)
    description: str | None = Field(max_length=EVENT_DESCRIPTION_MAX_LENGTH)
    type: Literal["local", "virtual"]
    starts_at: datetime
    ends_at: datetime | None
    location: str = Field(max_length=EVENT_LOCATION_MAX_LENGTH)
    latitude: float | None
    longitude: float | None
    contact_email: str | None = Field(max_length=EVENT_HOSTED_BY_CONTACT_EMAIL_MAX_LENGTH)
    contact_phone: str | None = Field(max_length=EVENT_HOSTED_BY_CONTACT_PHONE_MAX_LENGTH)
    price_cad: Decimal
    created_at: datetime
    app_status: Literal["pending", "approved", "rejected"]
    attendee_count: int