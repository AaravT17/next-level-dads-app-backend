from pydantic import BaseModel, Field
from uuid import UUID
from app.config.constants import MAX_BIO_LENGTH


class UserResponse(BaseModel):
    id: UUID
    name: str
    age: int = Field(ge=0)
    city: str
    province: str = Field(min_length=2, max_length=2)
    about: str = Field(max_length=MAX_BIO_LENGTH)
    avatar_url: str | None
    interests: list[str] = []
    children: list[str] = []
