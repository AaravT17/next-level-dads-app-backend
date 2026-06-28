from pydantic import BaseModel, Field
from uuid import UUID
from app.config.constants import MAX_NAME_LENGTH, MAX_CITY_LENGTH, MAX_BIO_LENGTH
from typing import Literal
from datetime import datetime, date


class UserResponse(BaseModel):
    id: UUID
    name: str = Field(max_length=MAX_NAME_LENGTH)
    age: int | None = Field(default=None, ge=0, le=200)
    date_of_birth: date | None = None
    city: str = Field(max_length=MAX_CITY_LENGTH)
    province: str = Field(min_length=2, max_length=2)
    about: str = Field(max_length=MAX_BIO_LENGTH)
    avatar_url: str | None
    interests: list[str] = []
    children: list[str] = []
    is_admin: bool = False


class UserProfileResponse(UserResponse):
    created_at: datetime
    connection_status: Literal['pending_incoming', 'pending_outgoing', 'connected', 'blocked'] | None = None


# TODO: The CommunityMemberResponse model contains fields not required/used by the frontend, can be trimmed
class CommunityMemberResponse(UserResponse):
    created_at: datetime
    joined_at: datetime
    role: Literal['admin', 'member'] = Field(default='member')


class UserStatsResponse(BaseModel):
    connections: int
    requests: int
    communities_joined: int
    events_registered_for: int
