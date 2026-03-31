from fastapi import APIRouter

from kairos.api import auth, blackout_days, calendar, events, projects, schedule, tags, tasks, views

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(tags.router, prefix="/tags", tags=["tags"])
api_router.include_router(views.router, prefix="/views", tags=["views"])
api_router.include_router(schedule.router, prefix="/schedule", tags=["schedule"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(blackout_days.router, prefix="/blackout-days", tags=["blackout-days"])
