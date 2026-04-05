from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Literal
from app.config.constants import MAX_BIO_LENGTH


class ConnectionCountResponse(BaseModel):
    connections: int
    requests: int


class ConnectionProfileResponse(BaseModel):
    id: UUID
    name: str
    age: int = Field(ge=0)
    city: str
    province: str = Field(min_length=2, max_length=2)
    about: str = Field(max_length=MAX_BIO_LENGTH)
    avatar_url: str | None
    interests: list[str] = []
    children: list[str] = []
    created_at: datetime
    connection_id: UUID
    connection_updated_at: datetime
    connection_status: (
        Literal["pending_incoming", "pending_outgoing", "connected", "blocked"] | None
    ) = None


class ConnectionStatusResponse(BaseModel):
    connection_status: (
        Literal["pending_incoming", "pending_outgoing", "connected", "blocked"] | None
    ) = None
