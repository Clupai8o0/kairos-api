from datetime import datetime, timezone

import pytest
from httpx import AsyncClient


def utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_calendar_accounts_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get("/calendar/accounts")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_event_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.post(
        "/events",
        json={
            "title": "Lecture",
            "start": "2026-04-01T10:00:00Z",
            "end": "2026-04-01T12:00:00Z",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_event_success(auth_client: AsyncClient, mock_gcal) -> None:
    response = await auth_client.post(
        "/events",
        json={
            "title": "Lecture",
            "start": "2026-04-01T10:00:00Z",
            "end": "2026-04-01T12:00:00Z",
            "description": "Linear algebra",
            "location": "Campus Room 2",
            "calendar_id": "work",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"] == "google"
    assert payload["title"] == "Lecture"
    assert payload["description"] == "Linear algebra"
    assert payload["location"] == "Campus Room 2"
    assert payload["calendar_id"] == "work"

    event_id = payload["event_id"]
    assert event_id in mock_gcal.events
    assert mock_gcal.events[event_id]["summary"] == "Lecture"
    assert mock_gcal.events[event_id]["calendar_id"] == "work"


@pytest.mark.asyncio
async def test_create_event_invalid_date_range_returns_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/events",
        json={
            "title": "Bad event",
            "start": "2026-04-01T12:00:00Z",
            "end": "2026-04-01T10:00:00Z",
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_date_range"


@pytest.mark.asyncio
async def test_calendar_accounts_multiple_calendars(auth_client: AsyncClient, mock_gcal) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="work",
        calendar_name="Work",
        access_role="writer",
    )
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="readonly",
        calendar_name="ReadOnly",
        access_role="reader",
    )
    mock_gcal.seed_calendar(
        account_id="acct_two",
        account_email="sam+two@test.com",
        calendar_id="personal",
        calendar_name="Personal",
        access_role="owner",
    )

    response = await auth_client.get("/calendar/accounts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    first = next(account for account in data if account["account_id"] == "acct_one")
    assert len(first["calendars"]) == 2
    readonly = next(c for c in first["calendars"] if c["calendar_id"] == "readonly")
    assert readonly["can_edit"] is False
    assert "is_free" in readonly


@pytest.mark.asyncio
async def test_get_calendar_event_detail(auth_client: AsyncClient, mock_gcal) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="work",
        calendar_name="Work",
        access_role="writer",
    )
    event_id = await mock_gcal.create_event(
        user=None,
        summary="Planning",
        start=utc(2026, 4, 1, 9, 0),
        end=utc(2026, 4, 1, 10, 0),
        account_id="acct_one",
        calendar_id="work",
        calendar_name="Work",
        description="Sprint planning",
    )

    response = await auth_client.get(
        f"/calendar/events/{event_id}",
        params={"account_id": "acct_one", "calendar_id": "work"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["event_id"] == event_id
    assert payload["summary"] == "Planning"


@pytest.mark.asyncio
async def test_patch_calendar_event_success(auth_client: AsyncClient, mock_gcal) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="work",
        calendar_name="Work",
        access_role="writer",
    )
    event_id = await mock_gcal.create_event(
        user=None,
        summary="Planning",
        start=utc(2026, 4, 1, 9, 0),
        end=utc(2026, 4, 1, 10, 0),
        account_id="acct_one",
        calendar_id="work",
        calendar_name="Work",
        etag="v1",
    )

    response = await auth_client.patch(
        f"/calendar/events/{event_id}",
        json={
            "account_id": "acct_one",
            "calendar_id": "work",
            "etag": "v1",
            "summary": "Planning updated",
            "description": "Now with agenda",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == "Planning updated"
    assert payload["description"] == "Now with agenda"
    assert payload["etag"] != "v1"


@pytest.mark.asyncio
async def test_patch_calendar_event_etag_conflict(auth_client: AsyncClient, mock_gcal) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="work",
        calendar_name="Work",
        access_role="writer",
    )
    event_id = await mock_gcal.create_event(
        user=None,
        summary="Planning",
        start=utc(2026, 4, 1, 9, 0),
        end=utc(2026, 4, 1, 10, 0),
        account_id="acct_one",
        calendar_id="work",
        calendar_name="Work",
        etag="v1",
    )

    response = await auth_client.patch(
        f"/calendar/events/{event_id}",
        json={
            "account_id": "acct_one",
            "calendar_id": "work",
            "etag": "v0",
            "summary": "Planning updated",
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "calendar_event_etag_mismatch"


@pytest.mark.asyncio
async def test_patch_calendar_event_read_only_returns_403(auth_client: AsyncClient, mock_gcal) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="readonly",
        calendar_name="ReadOnly",
        access_role="reader",
    )
    event_id = await mock_gcal.create_event(
        user=None,
        summary="Planning",
        start=utc(2026, 4, 1, 9, 0),
        end=utc(2026, 4, 1, 10, 0),
        account_id="acct_one",
        calendar_id="readonly",
        calendar_name="ReadOnly",
    )

    # mock marks event-level editability false for read-only calendar
    mock_gcal.events[event_id]["can_edit"] = False

    response = await auth_client.patch(
        f"/calendar/events/{event_id}",
        json={
            "account_id": "acct_one",
            "calendar_id": "readonly",
            "summary": "Planning updated",
        },
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "calendar_read_only"


@pytest.mark.asyncio
async def test_patch_calendar_selection_persists_and_returns_accounts(
    auth_client: AsyncClient, mock_gcal
) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="work",
        calendar_name="Work",
        access_role="writer",
        selected=True,
    )
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="personal",
        calendar_name="Personal",
        access_role="writer",
        selected=True,
    )

    response = await auth_client.patch(
        "/calendar/accounts/selection",
        json={
            "selections": [
                {"account_id": "acct_one", "calendar_id": "work", "selected": False},
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] == 1

    account = next(a for a in payload["accounts"] if a["account_id"] == "acct_one")
    work = next(c for c in account["calendars"] if c["calendar_id"] == "work")
    personal = next(c for c in account["calendars"] if c["calendar_id"] == "personal")
    assert work["selected"] is False
    assert personal["selected"] is True
    assert work["is_free"] is False

    # Re-fetch should return persisted value.
    get_response = await auth_client.get("/calendar/accounts")
    assert get_response.status_code == 200
    account = next(a for a in get_response.json() if a["account_id"] == "acct_one")
    work = next(c for c in account["calendars"] if c["calendar_id"] == "work")
    assert work["selected"] is False


@pytest.mark.asyncio
async def test_patch_calendar_selection_accepts_is_free_only(
    auth_client: AsyncClient,
    mock_gcal,
) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="work",
        calendar_name="Work",
        access_role="writer",
        selected=True,
        is_free=False,
    )

    response = await auth_client.patch(
        "/calendar/accounts/selection",
        json={
            "selections": [
                {"account_id": "acct_one", "calendar_id": "work", "is_free": True},
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] == 1

    account = next(a for a in payload["accounts"] if a["account_id"] == "acct_one")
    work = next(c for c in account["calendars"] if c["calendar_id"] == "work")
    assert work["selected"] is True
    assert work["is_free"] is True


@pytest.mark.asyncio
async def test_patch_calendar_selection_requires_selected_or_is_free(
    auth_client: AsyncClient,
    mock_gcal,
) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="work",
        calendar_name="Work",
        access_role="writer",
        selected=True,
    )

    response = await auth_client.patch(
        "/calendar/accounts/selection",
        json={
            "selections": [
                {"account_id": "acct_one", "calendar_id": "work"},
            ]
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_calendar_selection_idempotent(auth_client: AsyncClient, mock_gcal) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="work",
        calendar_name="Work",
        access_role="writer",
        selected=False,
    )

    response = await auth_client.patch(
        "/calendar/accounts/selection",
        json={
            "selections": [
                {"account_id": "acct_one", "calendar_id": "work", "selected": False},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["updated"] == 0


@pytest.mark.asyncio
async def test_patch_calendar_selection_unknown_pair_returns_422(
    auth_client: AsyncClient,
    mock_gcal,
) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="work",
        calendar_name="Work",
        access_role="writer",
        selected=True,
    )

    response = await auth_client.patch(
        "/calendar/accounts/selection",
        json={
            "selections": [
                {"account_id": "acct_one", "calendar_id": "unknown", "selected": False},
            ]
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "unknown_calendar_selection"
