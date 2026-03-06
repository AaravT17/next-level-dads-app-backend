from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from app.config.constants import (
    COMMUNITY_NAME_MAX_LENGTH,
    COMMUNITY_DESCRIPTION_MAX_LENGTH,
)


class CommunityResponse(BaseModel):
    id: UUID
    name: str = Field(max_length=COMMUNITY_NAME_MAX_LENGTH)
    description: str | None = Field(
        max_length=COMMUNITY_DESCRIPTION_MAX_LENGTH, default=None
    )
    member_count: int = Field(ge=0, default=0)
    created_by: UUID | None = None
    created_at: datetime
    is_member: bool = False
