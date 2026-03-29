import datetime as dt

from pydantic import BaseModel


class BlackoutDayCreate(BaseModel):
    date: dt.date
    reason: str | None = None


class BlackoutDayResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    date: dt.date
    reason: str | None
    created_at: dt.datetime
