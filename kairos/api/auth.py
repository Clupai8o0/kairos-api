from fastapi import APIRouter

router = APIRouter()


@router.get("/google/login")
async def google_login() -> dict:
    """Redirect to Google OAuth consent screen."""
    return {"detail": "Not implemented"}


@router.get("/google/callback")
async def google_callback() -> dict:
    """Handle Google OAuth callback."""
    return {"detail": "Not implemented"}
