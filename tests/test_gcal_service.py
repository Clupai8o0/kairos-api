"""Tests for GCalService — all calls go through MockGCalService, never real GCal."""

from datetime import datetime, timezone

import pytest

from tests.mocks import MockGCalService


@pytest.fixture
def gcal():
    return MockGCalService()


@pytest.fixture
def test_user(test_user):  # reuse conftest fixture
    return test_user


# ── get_free_busy ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_free_busy_empty(gcal, test_user) -> None:
    time_min = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    time_max = datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc)
    result = await gcal.get_free_busy(test_user, time_min, time_max)
    assert result == []


@pytest.mark.asyncio
async def test_get_free_busy_filters_by_range(gcal, test_user) -> None:
    t = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    gcal.add_busy_slot(
        start=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
    )
    gcal.add_busy_slot(  # outside query range — should be excluded
        start=datetime(2026, 4, 3, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 3, 10, 0, tzinfo=timezone.utc),
    )
    result = await gcal.get_free_busy(
        test_user,
        datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc),
    )
    assert len(result) == 1


# ── create_event ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_event_returns_id(gcal, test_user) -> None:
    event_id = await gcal.create_event(
        user=test_user,
        summary="Test task",
        start=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
    )
    assert event_id.startswith("mock_evt_")


@pytest.mark.asyncio
async def test_create_event_stores_event(gcal, test_user) -> None:
    await gcal.create_event(
        user=test_user,
        summary="My Task",
        start=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
    )
    assert len(gcal.events) == 1
    event = list(gcal.events.values())[0]
    assert event["summary"] == "My Task"


# ── update_event ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_event_modifies_summary(gcal, test_user) -> None:
    event_id = await gcal.create_event(
        user=test_user,
        summary="Old title",
        start=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
    )
    await gcal.update_event(user=test_user, event_id=event_id, summary="New title")
    assert gcal.events[event_id]["summary"] == "New title"


@pytest.mark.asyncio
async def test_update_nonexistent_event_is_noop(gcal, test_user) -> None:
    # Should not raise
    await gcal.update_event(user=test_user, event_id="no_such_id", summary="X")


# ── delete_event ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_event_removes_event(gcal, test_user) -> None:
    event_id = await gcal.create_event(
        user=test_user,
        summary="Delete me",
        start=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
    )
    await gcal.delete_event(user=test_user, event_id=event_id)
    assert event_id not in gcal.events


@pytest.mark.asyncio
async def test_delete_nonexistent_event_is_noop(gcal, test_user) -> None:
    # Should not raise
    await gcal.delete_event(user=test_user, event_id="ghost_event")


# ── get_events ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_events_filters_by_time_range(gcal, test_user) -> None:
    await gcal.create_event(
        user=test_user,
        summary="In range",
        start=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
    )
    await gcal.create_event(
        user=test_user,
        summary="Out of range",
        start=datetime(2026, 4, 3, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 3, 10, 0, tzinfo=timezone.utc),
    )
    result = await gcal.get_events(
        test_user,
        datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc),
    )
    assert len(result) == 1
    assert result[0]["summary"] == "In range"
