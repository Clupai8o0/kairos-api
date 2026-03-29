from datetime import datetime

from pydantic import BaseModel


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
    metadata: dict = {}


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
    metadata: dict | None = None


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
    metadata: dict
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
