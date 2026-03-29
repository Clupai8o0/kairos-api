from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_tasks() -> list:
    return []


@router.post("/", status_code=201)
async def create_task() -> dict:
    return {"detail": "Not implemented"}


@router.get("/{task_id}")
async def get_task(task_id: str) -> dict:
    return {"detail": "Not implemented"}


@router.patch("/{task_id}")
async def update_task(task_id: str) -> dict:
    return {"detail": "Not implemented"}


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str) -> None:
    return None
