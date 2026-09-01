from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Literal
from app.common.config.constants import MAX_BIO_LENGTH, CONNECTION_NOTE_MAX_LENGTH


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
    note: str | None = Field(None, max_length=CONNECTION_NOTE_MAX_LENGTH)
    connection_status: (
        Literal["pending_incoming", "pending_outgoing", "connected", "blocked"] | None
    ) = None


class SendConnectionRequestBody(BaseModel):
    """Optional payload for POST /api/connections/{target_user_id}.

    Every field is optional so the one-tap connect on the browse grid can keep
    posting no body at all.
    """

    note: str | None = Field(None, max_length=CONNECTION_NOTE_MAX_LENGTH)


class ConnectionStatusResponse(BaseModel):
    connection_status: (
        Literal["pending_incoming", "pending_outgoing", "connected", "blocked"] | None
    ) = None
