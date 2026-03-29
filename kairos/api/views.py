from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_views() -> list:
    return []


@router.post("/", status_code=201)
async def create_view() -> dict:
    return {"detail": "Not implemented"}


@router.get("/{view_id}")
async def get_view(view_id: str) -> dict:
    return {"detail": "Not implemented"}


@router.get("/{view_id}/tasks")
async def get_view_tasks(view_id: str) -> list:
    """Execute the view's filter and return matching tasks."""
    return []


@router.patch("/{view_id}")
async def update_view(view_id: str) -> dict:
    return {"detail": "Not implemented"}


@router.delete("/{view_id}", status_code=204)
async def delete_view(view_id: str) -> None:
    return None
