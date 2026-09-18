from typing import Literal

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

NotificationType = Literal[
    'connection_request',
    'connection_accepted',
    'chat_added',
    'community_activity',
]


class NotificationResponse(BaseModel):
    id: UUID
    type: NotificationType
    payload: dict
    created_at: datetime


class NotificationCountResponse(BaseModel):
    count: int = Field(ge=0)
