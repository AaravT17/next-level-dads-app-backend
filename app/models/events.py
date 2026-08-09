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
    """Used to capture a new event to be created"""
    name: str = Field(
        max_length=EVENT_NAME_MAX_LENGTH, 
        description="Event name"
    )
    description: str | None = Field(
        max_length=EVENT_DESCRIPTION_MAX_LENGTH, 
        default=None, 
        description="Event description"
    )
    type: Literal["local", "virtual"] = Field(
        description="Type of event"
    )
    starts_at: datetime = Field(
        description="Event start time and date"
    )
    ends_at: datetime | None = Field(
        default=None, 
        description="Event end time and date"
    )
    location: str = Field(
        max_length=EVENT_LOCATION_MAX_LENGTH, 
        description="Event location"
    )
    latitude: float | None = Field(
        default=None, 
        description="Latitude coordinate of the event"
    )
    longitude: float | None = Field(
        default=None, 
        description="Longitude coordinate of the event"
    )
    contact_email: str | None = Field(
        max_length=EVENT_HOSTED_BY_CONTACT_EMAIL_MAX_LENGTH, 
        default=None, 
        description="Contact person's email"
    )
    contact_phone: str | None = Field(
        max_length=EVENT_HOSTED_BY_CONTACT_PHONE_MAX_LENGTH, 
        default=None, 
        description="Contact person's phone number"
    )
    price_cad: Decimal = Field(
        description="Event price in Canadian dollars"
    )

# Return when new event is successfully created
class EventCreateResponse(BaseModel):
    """Returned on successful event creation"""
    id: UUID = Field(
        description="UUID of the newly created event application"
    )

# Model for event updates
class EventUpdate(BaseModel):
    """Fields that may be modified for an existing event"""
    name: str | None = Field(
        default=None,
        description="Event name"
    )
    description: str | None = Field(
        default=None,
        description="Event description"
    )
    type: str | None = Field(
        default=None,
        description="Type of event"
    )
    starts_at: datetime | None = Field(
        default=None,
        description="Event start time and date"
    )
    ends_at: datetime | None = Field(
        default=None,
        description="Event end time and date"
    )
    location: str | None = Field(
        default=None,
        description="Event location"
    )
    latitude: float | None = Field(
        default=None,
        description="Latitude coordinate of the event"
    ) 
    longitude: float | None = Field(
        default=None,
        description="Longitude coordinate of the event"
    ) 
    contact_email: str | None = Field(
        default=None,
        description="Contact person's email"
    ) 
    contact_phone: str | None = Field(
        default=None,
        description="Contact person's phone number"
    ) 
    price_cad: Decimal | None = Field(
        default=None,
        description="Event price in Canadian dollars"
    ) 

class EventUpdateResponse(BaseModel):
    id: UUID = Field(
        description="UUID if the event"
    )
    name: str = Field(
        max_length=EVENT_NAME_MAX_LENGTH,
        description="Event name"
    )
    description: str | None = Field(
        max_length=EVENT_DESCRIPTION_MAX_LENGTH,
        description="Event description"
    )
    type: Literal["local", "virtual"] = Field(
        description="Type of event"
    )
    starts_at: datetime = Field(
        description="Event start time and date"
    )
    ends_at: datetime | None = Field(
        description="Event end time and date"
    )
    location: str = Field(
        max_length=EVENT_LOCATION_MAX_LENGTH,
        description="Event location"
    )
    latitude: float | None = Field(
        description="Latitude coordinate of the event"
    )
    longitude: float | None = Field(
        description="Longitude coordinate of the event"
    )
    contact_email: str | None = Field(
        max_length=EVENT_HOSTED_BY_CONTACT_EMAIL_MAX_LENGTH,
        description="Contact person's email"
    )
    contact_phone: str | None = Field(
        max_length=EVENT_HOSTED_BY_CONTACT_PHONE_MAX_LENGTH,
        description="Contact person's phone number"
    )
    price_cad: Decimal = Field(
       description="Event price in Canadian dollars"
    )
    created_at: datetime = Field(
        description="Time and date the event was created"
    )
    app_status: Literal["pending", "approved", "rejected"] = Field(
        description="Application status"
    )


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
