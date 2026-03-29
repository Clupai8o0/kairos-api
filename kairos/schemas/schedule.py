from pydantic import BaseModel


class ScheduleRunRequest(BaseModel):
    task_ids: list[str] | None = None  # None = reschedule all pending


class ScheduleRunResponse(BaseModel):
    scheduled: int
    failed: int
    skipped: int
    details: list[dict] = []
