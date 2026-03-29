from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_tags() -> list:
    return []


@router.post("/", status_code=201)
async def create_tag() -> dict:
    return {"detail": "Not implemented"}


@router.patch("/{tag_id}")
async def update_tag(tag_id: str) -> dict:
    return {"detail": "Not implemented"}


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(tag_id: str) -> None:
    return None
