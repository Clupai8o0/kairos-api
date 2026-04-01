import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

DayOfWeek = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

_MAX_WINDOWS = 50


class ScheduleWindowCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    days_of_week: Annotated[list[DayOfWeek], Field(min_length=1)]
    start_time: dt.time
    end_time: dt.time
    color: str | None = None
    is_active: bool = True

    @field_validator("days_of_week")
    @classmethod
    def no_duplicates(cls, v: list[DayOfWeek]) -> list[DayOfWeek]:
        if len(v) != len(set(v)):
            raise ValueError("days_of_week must not contain duplicates")
        return v

    @model_validator(mode="after")
    def end_after_start(self) -> "ScheduleWindowCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be strictly after start_time")
        return self


class ScheduleWindowUpdate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    days_of_week: Annotated[list[DayOfWeek], Field(min_length=1)] | None = None
    start_time: dt.time | None = None
    end_time: dt.time | None = None
    color: str | None = None
    is_active: bool | None = None

    @field_validator("days_of_week")
    @classmethod
    def no_duplicates(cls, v: list[DayOfWeek] | None) -> list[DayOfWeek] | None:
        if v is not None and len(v) != len(set(v)):
            raise ValueError("days_of_week must not contain duplicates")
        return v

    @model_validator(mode="after")
    def end_after_start(self) -> "ScheduleWindowUpdate":
        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be strictly after start_time")
        return self


class ScheduleWindowResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    name: str
    days_of_week: list[str]
    start_time: dt.time
    end_time: dt.time
    color: str | None
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class ScheduleWindowListResponse(BaseModel):
    schedule_windows: list[ScheduleWindowResponse]
