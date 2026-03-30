from datetime import datetime, timezone

from kairos.services.gcal_service import GCalService


def test_parse_google_event_window_all_day() -> None:
    parsed = GCalService._parse_google_event_window(
        {"date": "2026-03-30"},
        {"date": "2026-03-31"},
    )
    assert parsed is not None
    start, end, is_all_day = parsed
    assert is_all_day is True
    assert start == datetime(2026, 3, 30, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 31, 0, 0, tzinfo=timezone.utc)


def test_parse_google_event_window_timed() -> None:
    parsed = GCalService._parse_google_event_window(
        {"dateTime": "2026-03-30T10:00:00+00:00"},
        {"dateTime": "2026-03-30T11:00:00+00:00"},
    )
    assert parsed is not None
    start, end, is_all_day = parsed
    assert is_all_day is False
    assert start == datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 30, 11, 0, tzinfo=timezone.utc)


def test_to_google_event_time_all_day_uses_date_field() -> None:
    payload = GCalService._to_google_event_time(
        datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc),
        is_all_day=True,
        timezone_name="Australia/Melbourne",
    )
    assert payload == {"date": "2026-03-30"}


def test_to_google_event_time_timed_uses_datetime() -> None:
    payload = GCalService._to_google_event_time(
        datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc),
        is_all_day=False,
        timezone_name="Australia/Melbourne",
    )
    assert payload["dateTime"].startswith("2026-03-30T14:00:00")
    assert payload["timeZone"] == "Australia/Melbourne"
