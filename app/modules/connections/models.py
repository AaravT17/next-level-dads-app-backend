from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from app.common.config.constants import CONNECTION_NOTE_MAX_LENGTH
from app.common.types import ConnectionStatus
from app.modules.users.models import UserBase


class ConnectionProfileResponse(UserBase):
    created_at: datetime
    connection_id: UUID
    connection_updated_at: datetime
    note: str | None = Field(None, max_length=CONNECTION_NOTE_MAX_LENGTH)
    connection_status: ConnectionStatus = None


class SendConnectionRequestBody(BaseModel):
    """Optional payload for POST /api/connections/{target_user_id}.

    Every field is optional so the one-tap connect on the browse grid can keep
    posting no body at all.
    """

    note: str | None = Field(None, max_length=CONNECTION_NOTE_MAX_LENGTH)


class ConnectionStatusResponse(BaseModel):
    connection_status: ConnectionStatus = None
