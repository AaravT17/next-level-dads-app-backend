from pydantic import BaseModel, Field, field_validator, model_validator


class CreateChatRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    participant_ids: list[str] = Field(..., min_length=1)

    @field_validator('name', mode='before')
    def validate_chat_name(cls, name: str):
        if name is None:
            return None
        return name.strip()

    @model_validator(mode='after')
    def validate_group_fields(self):
        if len(self.participant_ids) > 1 and not self.name:
            raise ValueError('Group chats require a name')
        if len(self.participant_ids) == 1 and self.name is not None:
            raise ValueError('DM chats cannot have a name')
        return self
