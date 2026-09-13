from pydantic import BaseModel
from uuid import UUID


class InterestResponse(BaseModel):
    id: UUID
    slug: str
    name: str
