from typing import Annotated

from pydantic import BaseModel, field_validator


class WorkHours(BaseModel):
    start: str  # "HH:MM" in 24-hour format
    end: str

    @field_validator("start", "end")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError("Time must be in HH:MM format")
        h, m = parts
        if not (h.isdigit() and m.isdigit()):
            raise ValueError("Time must be in HH:MM format")
        if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
            raise ValueError("Invalid hour or minute value")
        return v


class PreferencesResponse(BaseModel):
    work_hours: WorkHours
    timezone: str
    scheduling_horizon_days: int
    buffer_mins: int
    default_duration_mins: int


class PreferencesUpdate(BaseModel):
    work_hours: WorkHours | None = None
    timezone: str | None = None
    scheduling_horizon_days: int | None = None
    buffer_mins: int | None = None
    default_duration_mins: int | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyResponse(BaseModel):
    api_key: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None = None

    model_config = {"from_attributes": True}
