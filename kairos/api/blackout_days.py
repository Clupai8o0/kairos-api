from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_blackout_days() -> list:
    return []


@router.post("/", status_code=201)
async def create_blackout_day() -> dict:
    return {"detail": "Not implemented"}


@router.delete("/{blackout_day_id}", status_code=204)
async def delete_blackout_day(blackout_day_id: str) -> None:
    return None
