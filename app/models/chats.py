from pydantic import BaseModel, Field, field_validator, model_validator
from uuid import UUID
from datetime import datetime
from typing import Literal
from app.config.constants import MAX_NAME_LENGTH


class LastMessageResponse(BaseModel):
    id: UUID
    content: str
    sender_id: UUID | None = None
    sender_name: str | None = None
    created_at: datetime
    is_deleted: bool


class OtherUserResponse(BaseModel):
    id: UUID
    name: str
    avatar_url: str | None = None


class ChatResponse(BaseModel):
    id: UUID
    type: Literal['dm', 'group']
    name: str | None = None
    updated_at: datetime
    last_read_at: datetime | None = None
    last_message: LastMessageResponse | None = None
    other_user: OtherUserResponse | None = None


class ReplyToResponse(BaseModel):
    id: UUID
    content: str
    sender_id: UUID | None = None
    sender_name: str | None = None
    is_deleted: bool


class MessageResponse(BaseModel):
    id: UUID
    chat_id: UUID
    sender_id: UUID | None = None
    sender_name: str | None = None
    sender_avatar_url: str | None = None
    content: str
    reply_to: ReplyToResponse | None = None
    edited_at: datetime | None = None
    is_deleted: bool
    created_at: datetime


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    reply_to_id: UUID | None = None

    @field_validator('content', mode='before')
    def validate_content(cls, content: str):
        return content.strip()


class EditMessageRequest(BaseModel):
    new_content: str = Field(..., min_length=1, max_length=2000)

    @field_validator('new_content', mode='before')
    def validate_content(cls, new_content: str):
        return new_content.strip()


class EditMessageResponse(BaseModel):
    id: UUID
    content: str
    edited_at: datetime


class CreateChatRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    participant_ids: list[UUID] = Field(..., min_length=1)

    @field_validator('name', mode='before')
    def validate_chat_name(cls, name: str):
        if name is None:
            return None
        return name.strip()

    @field_validator('participant_ids', mode='before')
    def deduplicate_participant_ids(cls, participant_ids: list[UUID]):
        return list(set(participant_ids))

    @model_validator(mode='after')
    def validate_group_fields(self):
        if len(self.participant_ids) > 1 and not self.name:
            raise ValueError('Group chats require a name')
        if len(self.participant_ids) == 1 and self.name is not None:
            raise ValueError('DM chats cannot have a name')
        return self


class ChatParticipantResponse(BaseModel):
    id: UUID
    name: str = Field(max_length=MAX_NAME_LENGTH)
    avatar_url: str | None = None
    joined_at: datetime
    role: Literal['admin', 'member'] = Field(default='member')


class AddParticipantsRequest(BaseModel):
    new_participant_ids: list[UUID] = Field(..., min_length=1)

    @field_validator('new_participant_ids', mode='before')
    def deduplicate_participant_ids(cls, new_participant_ids: list[UUID]):
        return list(set(new_participant_ids))


class ChatAddableParticipantResponse(BaseModel):
    id: UUID
    name: str = Field(max_length=MAX_NAME_LENGTH)
    avatar_url: str | None = None
