from fastapi import APIRouter, Depends, HTTPException, status

from kairos.core.auth import get_current_user
from kairos.core.deps import get_gcal_service
from kairos.models.user import User
from kairos.schemas.calendar import CreateEventRequest, CreateEventResponse
from kairos.services.gcal_service import (
    GCalAuthError,
    GCalMissingScopeError,
    GCalPermissionError,
    GCalService,
)

router = APIRouter()


@router.post("", response_model=CreateEventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: CreateEventRequest,
    user: User = Depends(get_current_user),
    gcal: GCalService = Depends(get_gcal_service),
) -> CreateEventResponse:
    """Create a Google Calendar event directly (outside task scheduling)."""
    if payload.end <= payload.start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_date_range", "message": "end must be after start"},
        )

    calendar_id = payload.calendar_id or "primary"

    try:
        event_id = await gcal.create_event(
            user=user,
            summary=payload.title,
            start=payload.start,
            end=payload.end,
            description=payload.description,
            location=payload.location,
            calendar_id=calendar_id,
        )
    except GCalPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except GCalMissingScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": exc.code, "message": str(exc), "action": "reconsent_google"},
        ) from exc
    except GCalAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "google_auth_required", "message": str(exc), "action": "reconnect_google"},
        ) from exc

    return CreateEventResponse(
        event_id=event_id,
        title=payload.title,
        start=payload.start,
        end=payload.end,
        description=payload.description,
        location=payload.location,
        calendar_id=calendar_id,
    )
