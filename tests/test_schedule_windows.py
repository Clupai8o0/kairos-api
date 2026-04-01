"""Tests for the schedule windows API."""

import pytest
from httpx import AsyncClient


_VALID_WINDOW = {
    "name": "Gym",
    "days_of_week": ["MON", "WED", "FRI"],
    "start_time": "05:00:00",
    "end_time": "23:00:00",
    "color": "#10b981",
    "is_active": True,
}


# ── Create ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_schedule_window(auth_client: AsyncClient) -> None:
    r = await auth_client.post("/schedule-windows/", json=_VALID_WINDOW)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Gym"
    assert data["days_of_week"] == ["MON", "WED", "FRI"]
    assert data["start_time"] == "05:00:00"
    assert data["end_time"] == "23:00:00"
    assert data["color"] == "#10b981"
    assert data["is_active"] is True
    assert "id" in data
    assert "user_id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_window_minimal(auth_client: AsyncClient) -> None:
    """Only required fields — color defaults to null, is_active defaults to True."""
    r = await auth_client.post(
        "/schedule-windows/",
        json={"name": "Work", "days_of_week": ["MON", "TUE", "WED", "THU", "FRI"], "start_time": "09:00:00", "end_time": "17:00:00"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["color"] is None
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_window_end_before_start_rejected(auth_client: AsyncClient) -> None:
    r = await auth_client.post(
        "/schedule-windows/",
        json={**_VALID_WINDOW, "start_time": "20:00:00", "end_time": "08:00:00"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_window_equal_times_rejected(auth_client: AsyncClient) -> None:
    r = await auth_client.post(
        "/schedule-windows/",
        json={**_VALID_WINDOW, "start_time": "09:00:00", "end_time": "09:00:00"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_window_empty_days_rejected(auth_client: AsyncClient) -> None:
    r = await auth_client.post(
        "/schedule-windows/",
        json={**_VALID_WINDOW, "days_of_week": []},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_window_duplicate_days_rejected(auth_client: AsyncClient) -> None:
    r = await auth_client.post(
        "/schedule-windows/",
        json={**_VALID_WINDOW, "days_of_week": ["MON", "MON", "WED"]},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_window_blank_name_rejected(auth_client: AsyncClient) -> None:
    r = await auth_client.post(
        "/schedule-windows/",
        json={**_VALID_WINDOW, "name": "   "},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_window_name_too_long_rejected(auth_client: AsyncClient) -> None:
    r = await auth_client.post(
        "/schedule-windows/",
        json={**_VALID_WINDOW, "name": "x" * 101},
    )
    assert r.status_code == 422


# ── List ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_schedule_windows_empty(auth_client: AsyncClient) -> None:
    r = await auth_client.get("/schedule-windows/")
    assert r.status_code == 200
    data = r.json()
    assert data == {"schedule_windows": []}


@pytest.mark.asyncio
async def test_list_schedule_windows_returns_all(auth_client: AsyncClient) -> None:
    await auth_client.post("/schedule-windows/", json=_VALID_WINDOW)
    await auth_client.post(
        "/schedule-windows/",
        json={**_VALID_WINDOW, "name": "Evening", "start_time": "18:00:00", "end_time": "22:00:00"},
    )
    r = await auth_client.get("/schedule-windows/")
    assert r.status_code == 200
    assert len(r.json()["schedule_windows"]) == 2


# ── Update ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_schedule_window_name(auth_client: AsyncClient) -> None:
    create_r = await auth_client.post("/schedule-windows/", json=_VALID_WINDOW)
    window_id = create_r.json()["id"]

    r = await auth_client.patch(f"/schedule-windows/{window_id}", json={"name": "Yoga"})
    assert r.status_code == 200
    assert r.json()["name"] == "Yoga"


@pytest.mark.asyncio
async def test_update_schedule_window_toggle_active(auth_client: AsyncClient) -> None:
    create_r = await auth_client.post("/schedule-windows/", json=_VALID_WINDOW)
    window_id = create_r.json()["id"]

    r = await auth_client.patch(f"/schedule-windows/{window_id}", json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False


@pytest.mark.asyncio
async def test_update_schedule_window_partial_time_validates_against_existing(
    auth_client: AsyncClient,
) -> None:
    """Updating only end_time to be before the existing start_time should fail."""
    create_r = await auth_client.post(
        "/schedule-windows/",
        json={**_VALID_WINDOW, "start_time": "09:00:00", "end_time": "17:00:00"},
    )
    window_id = create_r.json()["id"]

    # Push end_time before existing start_time (09:00)
    r = await auth_client.patch(
        f"/schedule-windows/{window_id}", json={"end_time": "08:00:00"}
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_schedule_window_both_times(auth_client: AsyncClient) -> None:
    create_r = await auth_client.post("/schedule-windows/", json=_VALID_WINDOW)
    window_id = create_r.json()["id"]

    r = await auth_client.patch(
        f"/schedule-windows/{window_id}",
        json={"start_time": "07:00:00", "end_time": "15:00:00"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["start_time"] == "07:00:00"
    assert data["end_time"] == "15:00:00"


@pytest.mark.asyncio
async def test_update_nonexistent_window_returns_404(auth_client: AsyncClient) -> None:
    r = await auth_client.patch("/schedule-windows/nonexistent", json={"name": "Ghost"})
    assert r.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_schedule_window(auth_client: AsyncClient) -> None:
    create_r = await auth_client.post("/schedule-windows/", json=_VALID_WINDOW)
    window_id = create_r.json()["id"]

    del_r = await auth_client.delete(f"/schedule-windows/{window_id}")
    assert del_r.status_code == 204

    # Should no longer appear in list
    list_r = await auth_client.get("/schedule-windows/")
    assert list_r.json()["schedule_windows"] == []


@pytest.mark.asyncio
async def test_delete_nonexistent_window_returns_404(auth_client: AsyncClient) -> None:
    r = await auth_client.delete("/schedule-windows/nonexistent")
    assert r.status_code == 404


# ── Auth ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schedule_windows_require_auth(unauthed_client: AsyncClient) -> None:
    for method, path, body in [
        ("get", "/schedule-windows/", None),
        ("post", "/schedule-windows/", _VALID_WINDOW),
        ("patch", "/schedule-windows/some-id", {"name": "X"}),
        ("delete", "/schedule-windows/some-id", None),
    ]:
        fn = getattr(unauthed_client, method)
        r = await fn(path, json=body) if body else await fn(path)
        assert r.status_code == 401, f"{method.upper()} {path} should require auth"


# ── 50-window cap ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_window_over_limit_returns_400(auth_client: AsyncClient) -> None:
    """Creating more than 50 schedule windows returns 400."""
    for i in range(50):
        r = await auth_client.post(
            "/schedule-windows/",
            json={**_VALID_WINDOW, "name": f"Window {i}", "start_time": "09:00:00", "end_time": "10:00:00"},
        )
        assert r.status_code == 201

    r = await auth_client.post("/schedule-windows/", json={**_VALID_WINDOW, "name": "One too many"})
    assert r.status_code == 400
