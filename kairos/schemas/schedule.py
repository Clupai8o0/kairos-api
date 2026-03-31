from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from kairos.schemas.task import TaskResponse


class ScheduleRunRequest(BaseModel):
    task_ids: list[str] | None = None  # None = reschedule all pending
    calendar_ids: list[str] | None = None
    free_calendar_ids: list[str] | None = None


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
    event_id: str
    provider: Literal["google"] = "google"
    account_id: str
    calendar_id: str
    calendar_name: str
    summary: str
    description: str | None = None
    location: str | None = None
    start: datetime
    end: datetime
    timezone: str | None = None
    is_all_day: bool
    is_recurring_instance: bool
    recurring_event_id: str | None = None
    html_link: str | None = None
    can_edit: bool
    etag: str | None = None
    is_task_event: bool = False
    task_id: str | None = None
    transparency: Literal["opaque", "transparent"] = "opaque"


class ScheduleItem(BaseModel):
    type: Literal["task", "event"]
    task: TaskResponse | None = None
    gcal_event: GCalEventItem | None = None


class ScheduleTodayResponse(BaseModel):
    date: str  # YYYY-MM-DD
    items: list[ScheduleItem]

