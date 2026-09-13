from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from app.common.types import ConnectionStatus
from app.modules.users.models import UserBase


class ConnectionProfileResponse(UserBase):
    created_at: datetime
    connection_id: UUID
    connection_updated_at: datetime
    connection_status: ConnectionStatus = None


class ConnectionStatusResponse(BaseModel):
    connection_status: ConnectionStatus = None
