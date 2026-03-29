from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from kairos.schemas.task import TaskResponse


class ScheduleRunRequest(BaseModel):
    task_ids: list[str] | None = None  # None = reschedule all pending


class ScheduleRunResponse(BaseModel):
    scheduled: int
    failed: int
    skipped: int
    details: list[dict] = []


class FreeSlotResponse(BaseModel):
    start: datetime
    end: datetime
    duration_mins: float


class ScheduledTaskResponse(BaseModel):
    task_id: str
    title: str
    start: datetime
    end: datetime
    gcal_event_id: str | None


class GCalEventItem(BaseModel):
    id: str
    summary: str
    start: datetime
    end: datetime
    description: str | None = None


class ScheduleItem(BaseModel):
    type: Literal["task", "event"]
    task: TaskResponse | None = None
    gcal_event: GCalEventItem | None = None


class ScheduleTodayResponse(BaseModel):
    date: str  # YYYY-MM-DD
    items: list[ScheduleItem]

