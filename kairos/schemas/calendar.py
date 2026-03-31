from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator


class CalendarRef(BaseModel):
    calendar_id: str
    calendar_name: str
    timezone: str | None = None
    access_role: str
    can_edit: bool
    selected: bool
    is_free: bool
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
    transparency: Literal["opaque", "transparent"] = "opaque"


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
    transparency: Literal["opaque", "transparent"] | None = None


class CalendarSelectionItem(BaseModel):
    account_id: str
    calendar_id: str
    selected: bool | None = None
    is_free: bool | None = None

    @model_validator(mode="after")
    def validate_selection_payload(self):
        if self.selected is None and self.is_free is None:
            raise ValueError("At least one of selected or is_free must be provided")
        return self


class UpdateCalendarSelectionRequest(BaseModel):
    selections: list[CalendarSelectionItem]


class UpdateCalendarSelectionResponse(BaseModel):
    updated: int
    accounts: list[ConnectedAccountResponse]


class CreateEventRequest(BaseModel):
    title: str
    start: datetime
    end: datetime
    description: str | None = None
    location: str | None = None
    calendar_id: str | None = None


class CreateEventResponse(BaseModel):
    event_id: str
    provider: Literal["google"] = "google"
    title: str
    start: datetime
    end: datetime
    description: str | None = None
    location: str | None = None
    calendar_id: str
