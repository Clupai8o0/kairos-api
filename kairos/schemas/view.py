from datetime import datetime

from pydantic import BaseModel


class ViewCreate(BaseModel):
    name: str
    icon: str | None = None
    filter_config: dict
    sort_config: dict = {"field": "priority", "direction": "asc"}


class ViewUpdate(BaseModel):
    name: str | None = None
    icon: str | None = None
    position: int | None = None
    filter_config: dict | None = None
    sort_config: dict | None = None


class ViewResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    name: str
    icon: str | None
    is_default: bool
    position: int
    filter_config: dict
    sort_config: dict
    created_at: datetime
    updated_at: datetime
