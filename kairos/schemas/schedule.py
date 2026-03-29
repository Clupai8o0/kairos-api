from datetime import datetime

from pydantic import BaseModel


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

