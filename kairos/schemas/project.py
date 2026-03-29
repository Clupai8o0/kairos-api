from datetime import datetime

from pydantic import BaseModel


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
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    title: str
    description: str | None
    deadline: datetime | None
    status: str
    color: str | None
    metadata: dict
    created_at: datetime
    updated_at: datetime
