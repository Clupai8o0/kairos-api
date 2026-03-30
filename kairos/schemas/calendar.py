from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CalendarRef(BaseModel):
    calendar_id: str
    calendar_name: str
    timezone: str | None = None
    access_role: str
    can_edit: bool
    selected: bool
    is_primary: bool


class ConnectedAccountResponse(BaseModel):
    account_id: str
    email: str
    display_name: str | None = None
    calendars: list[CalendarRef]


class EventDetailResponse(BaseModel):
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


class UpdateEventRequest(BaseModel):
    account_id: str
    calendar_id: str
    etag: str | None = None
    mode: Literal["single", "series"] = "single"
    summary: str | None = None
    description: str | None = None
    location: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    timezone: str | None = None
