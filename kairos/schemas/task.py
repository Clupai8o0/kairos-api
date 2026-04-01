from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from kairos.schemas.tag import TagResponse

_DEFAULT_MIN_CHUNK_MINS = 30
_MINIMUM_CHUNK_MINS = 5


class RecurrenceRule(BaseModel):
    freq: Literal["daily", "weekly", "monthly", "yearly"]
    interval: int = 1
    days_of_week: list[str] | None = None  # e.g. ["MON", "WED"] — weekly only
    end_date: date | None = None
    end_after_count: int | None = None

    @field_validator("interval")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("interval must be >= 1")
        return v

    @model_validator(mode="after")
    def validate_end_condition(self) -> "RecurrenceRule":
        if self.end_date is not None and self.end_after_count is not None:
            raise ValueError("end_date and end_after_count are mutually exclusive")
        return self


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
    recurrence_rule: RecurrenceRule | None = None

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

    @field_validator("min_chunk_mins")
    @classmethod
    def validate_min_chunk_mins(cls, v: int | None) -> int | None:
        if v is not None and v < _MINIMUM_CHUNK_MINS:
            raise ValueError(f"min_chunk_mins must be at least {_MINIMUM_CHUNK_MINS}")
        return v

    @model_validator(mode="after")
    def apply_splittable_defaults(self) -> "TaskCreate":
        if self.is_splittable and self.min_chunk_mins is None:
            self.min_chunk_mins = _DEFAULT_MIN_CHUNK_MINS
        return self


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
    recurrence_rule: RecurrenceRule | None = None

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

    @field_validator("min_chunk_mins")
    @classmethod
    def validate_min_chunk_mins(cls, v: int | None) -> int | None:
        if v is not None and v < _MINIMUM_CHUNK_MINS:
            raise ValueError(f"min_chunk_mins must be at least {_MINIMUM_CHUNK_MINS}")
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
    recurrence_rule: dict | None = None
    parent_task_id: str | None = None
    recurrence_index: int | None = None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
    limit: int
    offset: int
