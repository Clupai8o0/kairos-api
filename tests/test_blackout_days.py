import datetime as dt

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.blackout_day import BlackoutDay
from kairos.models.task import Task, TaskStatus
from kairos.models.user import User
from kairos.services.scheduler import run_scheduler
from tests.mocks import MockGCalService


# ── Create ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_blackout_day(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/blackout-days/", json={"date": "2026-05-01", "reason": "Public holiday"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["date"] == "2026-05-01"
    assert data["reason"] == "Public holiday"
    assert "id" in data
    assert "user_id" in data


@pytest.mark.asyncio
async def test_create_blackout_day_without_reason(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/blackout-days/", json={"date": "2026-05-02"}
    )
    assert response.status_code == 201
    assert response.json()["reason"] is None


@pytest.mark.asyncio
async def test_create_duplicate_blackout_returns_409(auth_client: AsyncClient) -> None:
    await auth_client.post("/blackout-days/", json={"date": "2026-06-01"})
    response = await auth_client.post("/blackout-days/", json={"date": "2026-06-01"})
    assert response.status_code == 409


# ── List ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_blackout_days_empty(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/blackout-days/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_blackout_days(auth_client: AsyncClient) -> None:
    await auth_client.post("/blackout-days/", json={"date": "2026-07-01"})
    await auth_client.post("/blackout-days/", json={"date": "2026-07-04"})

    response = await auth_client.get("/blackout-days/")
    assert response.status_code == 200
    dates = [d["date"] for d in response.json()]
    assert "2026-07-01" in dates
    assert "2026-07-04" in dates


@pytest.mark.asyncio
async def test_list_blackout_days_date_from_filter(auth_client: AsyncClient) -> None:
    await auth_client.post("/blackout-days/", json={"date": "2026-08-01"})
    await auth_client.post("/blackout-days/", json={"date": "2026-08-15"})

    response = await auth_client.get("/blackout-days/?date_from=2026-08-10")
    assert response.status_code == 200
    dates = [d["date"] for d in response.json()]
    assert "2026-08-15" in dates
    assert "2026-08-01" not in dates


@pytest.mark.asyncio
async def test_list_blackout_days_date_to_filter(auth_client: AsyncClient) -> None:
    await auth_client.post("/blackout-days/", json={"date": "2026-09-01"})
    await auth_client.post("/blackout-days/", json={"date": "2026-09-20"})

    response = await auth_client.get("/blackout-days/?date_to=2026-09-10")
    assert response.status_code == 200
    dates = [d["date"] for d in response.json()]
    assert "2026-09-01" in dates
    assert "2026-09-20" not in dates


# ── Delete ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_blackout_day(auth_client: AsyncClient) -> None:
    create_resp = await auth_client.post(
        "/blackout-days/", json={"date": "2026-10-01"}
    )
    day_id = create_resp.json()["id"]

    delete_resp = await auth_client.delete(f"/blackout-days/{day_id}")
    assert delete_resp.status_code == 204

    list_resp = await auth_client.get("/blackout-days/")
    dates = [d["date"] for d in list_resp.json()]
    assert "2026-10-01" not in dates


@pytest.mark.asyncio
async def test_delete_nonexistent_blackout_day_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.delete("/blackout-days/nonexistent_id")
    assert response.status_code == 404


# ── Auth guard ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_blackout_days_require_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get("/blackout-days/")
    assert response.status_code == 401


# ── Scheduler integration ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scheduler_skips_blackout_day(
    db_session: AsyncSession, test_user: User
) -> None:
    """Tasks are not placed on blackout dates — if all horizon days are blacked out,
    the scheduler fails to find a slot rather than placing the task on a blackout day."""
    gcal = MockGCalService()

    task = Task(
        id="blackout_task_1",
        user_id=test_user.id,
        title="Task on blacked-out day",
        duration_mins=60,
        priority=3,
        status=TaskStatus.PENDING,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=[],
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        metadata_json={},
    )
    db_session.add(task)

    # Block every day in the scheduling horizon (14 days)
    today = dt.date.today()
    for offset in range(15):
        day = BlackoutDay(
            user_id=test_user.id,
            date=today + dt.timedelta(days=offset),
        )
        db_session.add(day)

    await db_session.commit()

    result = await run_scheduler(db_session, gcal, test_user)

    # No slot available → task not scheduled
    assert result.scheduled == 0
    assert len(gcal.events) == 0
    await db_session.refresh(task)
    assert task.gcal_event_id is None

