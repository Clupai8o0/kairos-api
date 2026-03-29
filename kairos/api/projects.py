from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_projects() -> list:
    return []


@router.post("/", status_code=201)
async def create_project() -> dict:
    return {"detail": "Not implemented"}


@router.get("/{project_id}")
async def get_project(project_id: str) -> dict:
    return {"detail": "Not implemented"}


@router.patch("/{project_id}")
async def update_project(project_id: str) -> dict:
    return {"detail": "Not implemented"}


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str) -> None:
    return None
