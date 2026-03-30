from collections import defaultdict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.deps import get_db, get_gcal_service
from kairos.models.user import User
from kairos.schemas.calendar import (
    CalendarRef,
    ConnectedAccountResponse,
    EventDetailResponse,
    UpdateEventRequest,
)
from kairos.services.gcal_service import (
    GCalAuthError,
    GCalConflictError,
    GCalMissingScopeError,
    GCalNotFoundError,
    GCalPermissionError,
    GCalService,
)

router = APIRouter()


@router.get("/accounts", response_model=list[ConnectedAccountResponse])
async def list_connected_accounts(
    user: User = Depends(get_current_user),
    gcal: GCalService = Depends(get_gcal_service),
) -> list[ConnectedAccountResponse]:
    """List connected Google accounts and calendars with edit capability flags."""
    try:
        infos = await gcal.list_connected_calendars(user)
    except GCalMissingScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": exc.code,
                "message": str(exc),
                "action": "reconsent_google",
            },
        ) from exc
    except GCalAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "google_auth_required",
                "message": str(exc),
                "action": "reconnect_google",
            },
        ) from exc

    grouped: dict[str, dict] = defaultdict(lambda: {"email": "", "calendars": []})
    for info in infos:
        grouped[info.account_id]["email"] = info.account_email
        grouped[info.account_id]["calendars"].append(
            CalendarRef(
                calendar_id=info.calendar_id,
                calendar_name=info.calendar_name,
                timezone=info.timezone,
                access_role=info.access_role,
                can_edit=info.access_role in {"owner", "writer"},
                selected=info.selected,
                is_primary=info.is_primary,
            )
        )

    return [
        ConnectedAccountResponse(
            account_id=account_id,
            email=value["email"],
            calendars=value["calendars"],
        )
        for account_id, value in grouped.items()
    ]


@router.get("/events/{event_id}", response_model=EventDetailResponse)
async def get_event_detail(
    event_id: str,
    account_id: str = Query(...),
    calendar_id: str = Query(...),
    user: User = Depends(get_current_user),
    gcal: GCalService = Depends(get_gcal_service),
) -> EventDetailResponse:
    """Return a specific Google event for edit prefill."""
    try:
        event = await gcal.get_event_detail(user, event_id, account_id, calendar_id)
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
    except GCalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "calendar_event_not_found", "message": str(exc)},
        ) from exc
    except GCalAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "google_auth_required", "message": str(exc)},
        ) from exc

    return EventDetailResponse(**event.__dict__)


@router.patch("/events/{event_id}", response_model=EventDetailResponse)
async def patch_event(
    event_id: str,
    payload: UpdateEventRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    gcal: GCalService = Depends(get_gcal_service),
) -> EventDetailResponse:
    """Update an editable Google event. Supports optimistic concurrency via etag."""
    if payload.timezone is not None:
        try:
            ZoneInfo(payload.timezone)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_timezone", "message": f"Unsupported timezone: {payload.timezone}"},
            ) from exc

    if payload.start and payload.end and payload.end <= payload.start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_date_range", "message": "end must be after start"},
        )

    try:
        event = await gcal.patch_event(
            user,
            event_id,
            payload.account_id,
            payload.calendar_id,
            etag=payload.etag,
            mode=payload.mode,
            summary=payload.summary,
            description=payload.description,
            location=payload.location,
            start=payload.start,
            end=payload.end,
            timezone_name=payload.timezone,
        )
    except GCalConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "calendar_event_etag_mismatch",
                "message": str(exc),
                "action": "refetch_event",
            },
        ) from exc
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
    except GCalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "calendar_event_not_found", "message": str(exc)},
        ) from exc
    except GCalAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "google_auth_required", "message": str(exc), "action": "reconnect_google"},
        ) from exc

    await db.flush()
    return EventDetailResponse(**event.__dict__)
