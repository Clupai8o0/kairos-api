from fastapi import APIRouter

router = APIRouter()


@router.post("/run")
async def run_schedule() -> dict:
    """Trigger a full scheduling run."""
    return {"detail": "Not implemented"}


@router.get("/today")
async def schedule_today() -> list:
    """Get today's scheduled tasks."""
    return []


@router.get("/week")
async def schedule_week() -> list:
    """Get this week's scheduled tasks."""
    return []


@router.get("/free-slots")
async def free_slots() -> list:
    """Get available time slots."""
    return []
