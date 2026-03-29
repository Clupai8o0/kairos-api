from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from kairos.schemas.tag import TagResponse


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    duration_mins: int | None = None
    deadline: datetime | None = None
    priority: int = 3
    project_id: str | None = None
    tag_ids: list[str] = []
    schedulable: bool = True
    is_splittable: bool = False
    min_chunk_mins: int | None = None
    depends_on: list[str] = []
    buffer_mins: int = 15
    metadata: dict = {}

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int) -> int:
        if v not in (1, 2, 3, 4):
            raise ValueError("priority must be 1, 2, 3, or 4")
        return v

    @field_validator("duration_mins")
    @classmethod
    def validate_duration(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("duration_mins must be a positive integer")
        return v


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    duration_mins: int | None = None
    deadline: datetime | None = None
    priority: int | None = None
    project_id: str | None = None
    tag_ids: list[str] | None = None
    status: str | None = None
    schedulable: bool | None = None
    is_splittable: bool | None = None
    min_chunk_mins: int | None = None
    depends_on: list[str] | None = None
    buffer_mins: int | None = None
    metadata: dict | None = None

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int | None) -> int | None:
        if v is not None and v not in (1, 2, 3, 4):
            raise ValueError("priority must be 1, 2, 3, or 4")
        return v

    @field_validator("duration_mins")
    @classmethod
    def validate_duration(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("duration_mins must be a positive integer")
        return v


class TaskResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    project_id: str | None
    title: str
    description: str | None
    duration_mins: int | None
    deadline: datetime | None
    priority: int
    status: str
    schedulable: bool
    gcal_event_id: str | None
    scheduled_at: datetime | None
    scheduled_end: datetime | None
    buffer_mins: int
    min_chunk_mins: int | None
    is_splittable: bool
    depends_on: list[str]
    # The ORM attribute is named metadata_json (column alias to avoid SQLAlchemy's
    # reserved Base.metadata name). We map it back to "metadata" in the API response.
    metadata: dict = Field(validation_alias="metadata_json", default={})
    tags: list[TagResponse] = []
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
    limit: int
    offset: int
