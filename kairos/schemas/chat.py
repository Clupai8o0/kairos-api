from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class ChatMessage(BaseModel):
    """A single message in a chat session (matches the frontend ChatApiMessage shape)."""

    role: Literal["user", "assistant"]
    content: str | list[dict]


class ChatSessionCreate(BaseModel):
    messages: list[ChatMessage]

    @field_validator("messages")
    @classmethod
    def messages_not_empty(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        if not v:
            raise ValueError("messages must not be empty")
        return v


class ChatSessionUpdate(BaseModel):
    """Append or replace messages in an existing session."""

    messages: list[ChatMessage]

    @field_validator("messages")
    @classmethod
    def messages_not_empty(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        if not v:
            raise ValueError("messages must not be empty")
        return v


class ChatSessionResponse(BaseModel):
    model_config = {"from_attributes": True}

    session_id: str
    messages: list[ChatMessage]
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatSessionSummary(BaseModel):
    """Lightweight list item — messages are omitted."""

    model_config = {"from_attributes": True}

    session_id: str
    message_count: int
    preview: str
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionSummary]
    total: int
