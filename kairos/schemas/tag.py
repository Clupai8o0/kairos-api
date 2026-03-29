from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str | None = None
    icon: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    color: str | None = None
    icon: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("name must not be empty")
        return v


class TagResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    name: str
    color: str | None
    icon: str | None
    created_at: datetime


class TagWithCountsResponse(BaseModel):
    id: str
    user_id: str
    name: str
    color: str | None
    icon: str | None
    created_at: datetime
    task_count: int
    project_count: int


class TagListResponse(BaseModel):
    tags: list[TagWithCountsResponse]
