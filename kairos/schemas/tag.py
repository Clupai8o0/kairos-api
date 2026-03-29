from datetime import datetime

from pydantic import BaseModel


class TagCreate(BaseModel):
    name: str
    color: str | None = None
    icon: str | None = None


class TagUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    icon: str | None = None


class TagResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    name: str
    color: str | None
    icon: str | None
    created_at: datetime
