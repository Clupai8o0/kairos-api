# Google Calendar Integration

Kairos uses Google Calendar API v3 as the time source of truth.
All calendar operations go through `services/gcal_service.py`.

Current implementation supports merged event reads across all linked Google
accounts and selected calendars, plus in-app event detail + update APIs.

---

## Table of Contents
1. [OAuth Setup](#oauth-setup)
2. [Core Operations](#core-operations)
3. [Free/Busy Queries](#freebusy-queries)
4. [Event CRUD](#event-crud)
5. [Token Management](#token-management)
6. [Error Handling](#error-handling)
7. [Testing Strategy](#testing-strategy)

---

## OAuth Setup

### Google Cloud Console

1. Create a project in Google Cloud Console
2. Enable **Google Calendar API**
3. Create OAuth 2.0 Client ID (Web application)
4. Set authorised redirect URI: `http://localhost:8000/api/v1/auth/google/callback`
5. Download client credentials JSON

### Required Scopes

```python
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",        # Full calendar access
]
```

Using `auth/calendar` (not `auth/calendar.readonly`) because we need to write events.

If write scope is missing, API returns `403` with code `calendar_write_scope_missing`
and an action hint to trigger re-consent.

---

## Core Operations

`gcal_service.py` wraps all Google Calendar interactions:

```python
class GCalService:
    """Async wrapper around Google Calendar API."""

    async def get_free_busy(
        self,
        user: User,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
    ) -> list[BusySlot]:
        """Get busy time ranges from Google Calendar."""

    async def create_event(
        self,
        user: User,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
        calendar_id: str = "primary",
    ) -> str:
        """Create a calendar event. Returns the event ID."""

    async def update_event(
        self,
        user: User,
        event_id: str,
        summary: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        description: str | None = None,
        calendar_id: str = "primary",
    ) -> None:
        """Update an existing calendar event."""

    async def delete_event(
        self,
        user: User,
        event_id: str,
        calendar_id: str = "primary",
    ) -> None:
        """Delete a calendar event."""

    async def get_events(
        self,
        user: User,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
    ) -> list[GCalEvent]:
        """List all events in a time range (for schedule/today endpoint)."""

    async def list_connected_calendars(self, user: User) -> list[GoogleCalendarInfo]:
        """Return linked accounts and calendar metadata (selected/read-only/write)."""

    async def get_schedule_events(
        self,
        user: User,
        time_min: datetime,
        time_max: datetime,
    ) -> list[GoogleScheduleEvent]:
        """Merged events from all selected calendars across all linked accounts."""

    async def get_event_detail(
        self,
        user: User,
        event_id: str,
        account_id: str,
        calendar_id: str,
    ) -> GoogleScheduleEvent:
        """Fetch one event for edit prefill."""

    async def patch_event(
        self,
        user: User,
        event_id: str,
        account_id: str,
        calendar_id: str,
        *,
        etag: str | None,
        mode: str,
        summary: str | None,
        description: str | None,
        location: str | None,
        start: datetime | None,
        end: datetime | None,
        timezone_name: str | None,
    ) -> GoogleScheduleEvent:
        """Patch event or recurring series with optimistic concurrency."""
```

---

## Free/Busy Queries

The scheduler's primary input. Returns busy time ranges — the scheduler inverts these
to find free slots.

### API Call

```python
async def get_free_busy(self, user: User, time_min: datetime, time_max: datetime) -> list[BusySlot]:
    credentials = self._get_credentials(user)
    service = build("calendar", "v3", credentials=credentials)

    body = {
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "items": [{"id": user.preferences.get("calendar_id", "primary")}],
    }

    # Use httpx for async (google-api-python-client is sync)
    # Option A: Run in executor
    # Option B: Use raw HTTP with httpx
    result = await asyncio.to_thread(
        service.freebusy().query(body=body).execute
    )

    busy_slots = []
    for busy in result["calendars"]["primary"]["busy"]:
        busy_slots.append(BusySlot(
            start=datetime.fromisoformat(busy["start"]),
            end=datetime.fromisoformat(busy["end"]),
        ))
    return busy_slots
```

### Inverting Busy → Free Slots

```python
def get_free_slots(
    busy_slots: list[BusySlot],
    day_start: datetime,
    day_end: datetime,
    work_start: time,
    work_end: time,
) -> list[FreeSlot]:
    """
    Given busy periods and work hours, calculate free time slots.

    1. Clip to work hours (e.g., 09:00-17:00)
    2. Subtract busy periods
    3. Return remaining free blocks
    """
    # Start with full work hours as one big free slot
    free = [FreeSlot(start=day_start.replace(hour=work_start.hour, minute=work_start.minute),
                     end=day_start.replace(hour=work_end.hour, minute=work_end.minute))]

    # Subtract each busy period
    for busy in sorted(busy_slots, key=lambda b: b.start):
        new_free = []
        for slot in free:
            if busy.end <= slot.start or busy.start >= slot.end:
                new_free.append(slot)  # No overlap
            else:
                if busy.start > slot.start:
                    new_free.append(FreeSlot(start=slot.start, end=busy.start))
                if busy.end < slot.end:
                    new_free.append(FreeSlot(start=busy.end, end=slot.end))
        free = new_free

    return [s for s in free if (s.end - s.start).total_seconds() >= 300]  # min 5 min
```

---

## Event CRUD

### Creating Events

```python
event_body = {
    "summary": task.title,
    "description": f"Kairos task: {task.id}",
    "start": {
        "dateTime": start.isoformat(),
        "timeZone": user.preferences.get("timezone", "Australia/Melbourne"),
    },
    "end": {
        "dateTime": end.isoformat(),
        "timeZone": user.preferences.get("timezone", "Australia/Melbourne"),
    },
    "extendedProperties": {
        "private": {
            "kairos_task_id": task.id,
            "kairos_managed": "true",
        }
    },
}
```

**Important:** We use `extendedProperties` to tag events created by Kairos. This lets us:
- Identify our events vs. user-created events
- Avoid modifying events we didn't create
- Clean up orphaned events

### Updating Events

Only update Kairos-managed events (check `extendedProperties`).
Partial updates: only send fields that changed.

### Deleting Events

Called when:
- Task is completed (time block no longer needed)
- Task is cancelled
- Task is unscheduled
- Task is rescheduled (old event deleted, new event created)

---

## Token Management

Google OAuth tokens expire. Handle refresh transparently.

```python
def _get_credentials(self, user: User) -> Credentials:
    creds = Credentials(
        token=user.google_access_token,
        refresh_token=user.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        expiry=user.google_token_expiry,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Update stored tokens
        # (pass db session to update user record)

    return creds
```

**Critical:** Store the refresh token on first OAuth. If the user revokes access,
handle the `InvalidGrantError` gracefully — mark user as needing re-auth.

---

## Error Handling

| Error | Cause | Response |
|-------|-------|----------|
| `HttpError 401` | Token expired/revoked | Refresh token, retry once |
| `HttpError 403` | Insufficient permissions | User needs to re-authorize |
| `HttpError 404` | Event deleted externally | Clear gcal_event_id, mark unscheduled |
| `HttpError 409` | Conflict (slot taken) | Retry with next available slot |
| `HttpError 429` | Rate limited | Back off, retry with exponential delay |
| Network timeout | GCal unreachable | Return task with scheduled_at=null |

### Rate Limits

Google Calendar API allows:
- 1,000,000 queries/day (free tier)
- 500 requests/100 seconds/user
- Batch requests supported (future optimisation)

For single-user v1, rate limits won't be an issue.

Reliability additions:
- Retries with exponential backoff for `429`, `500`, `503`, and transient network errors
- Cached Google `calendarList` responses for 5 minutes per linked account
- Concurrent event window fetches with bounded concurrency for week views

---

## Testing Strategy

**Do NOT call the real Google Calendar API in tests.**

### Mock Strategy

```python
# tests/conftest.py

class MockGCalService:
    def __init__(self):
        self.events: dict[str, dict] = {}
        self.busy_slots: list[BusySlot] = []

    async def get_free_busy(self, user, time_min, time_max, **kwargs):
        return [s for s in self.busy_slots if s.end > time_min and s.start < time_max]

    async def create_event(self, user, summary, start, end, **kwargs):
        event_id = f"mock_event_{len(self.events)}"
        self.events[event_id] = {"summary": summary, "start": start, "end": end}
        return event_id

    async def delete_event(self, user, event_id, **kwargs):
        self.events.pop(event_id, None)

    async def get_events(self, user, time_min, time_max, **kwargs):
        return [e for e in self.events.values()
                if e["end"] > time_min and e["start"] < time_max]


@pytest.fixture
def mock_gcal():
    return MockGCalService()
```

Inject `MockGCalService` via dependency override in test client:

```python
app.dependency_overrides[get_gcal_service] = lambda: mock_gcal
```

This lets you test the scheduler end-to-end without GCal API calls.

For calendar APIs, mocks should also cover:
- multiple accounts and calendars
- read-only calendar (`calendar_read_only`)
- etag conflict (`calendar_event_etag_mismatch`)
- recurring instance metadata (`is_recurring_instance`, `recurring_event_id`)