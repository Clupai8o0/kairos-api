from datetime import datetime

from pydantic import BaseModel, Field

from kairos.schemas.tag import TagResponse


class TaskSummary(BaseModel):
    """Minimal task representation embedded inside a project detail response."""

    model_config = {"from_attributes": True}

    id: str
    title: str
    status: str
    priority: int
    scheduled_at: datetime | None


class ProjectCreate(BaseModel):
    title: str
    description: str | None = None
    deadline: datetime | None = None
    color: str | None = None
    tag_ids: list[str] = []
    metadata: dict = {}


class ProjectUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    deadline: datetime | None = None
    status: str | None = None
    color: str | None = None
    tag_ids: list[str] | None = None
    metadata: dict | None = None


class ProjectResponse(BaseModel):
    model_config = {"from_attributes": True, "populate_by_name": True}

    id: str
    user_id: str
    title: str
    description: str | None
    deadline: datetime | None
    status: str
    color: str | None
    # ORM attribute is metadata_json (column alias to avoid SQLAlchemy reserved name)
    metadata: dict = Field(validation_alias="metadata_json", default={})
    tags: list[TagResponse] = []
    created_at: datetime
    updated_at: datetime


class ProjectWithTasksResponse(ProjectResponse):
    """Extended project response that includes a summary of nested tasks."""

    tasks: list[TaskSummary] = []


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    total: int
    limit: int
    offset: int
