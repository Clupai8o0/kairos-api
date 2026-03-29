"""Google Calendar API wrapper — read free/busy, write events, delete events."""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.config import settings
from kairos.models.user import User


@dataclass
class BusySlot:
    start: datetime
    end: datetime


@dataclass
class GCalEvent:
    id: str
    summary: str
    start: datetime
    end: datetime
    description: str | None = None
    kairos_task_id: str | None = None


class GCalAuthError(Exception):
    """Raised when the user needs to re-authorise Google Calendar access."""


class GCalService:
    """Async wrapper around Google Calendar API v3."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        # db is optional — only needed when token refresh requires persisting new tokens
        self._db = db

    # ── Credentials ────────────────────────────────────────────────────────────

    def _get_credentials(self, user: User) -> Credentials:
        """Build credentials from user tokens, refreshing if expired."""
        creds = Credentials(
            token=user.google_access_token,
            refresh_token=user.google_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            expiry=user.google_token_expiry,
        )
        return creds

    def _refresh_credentials(self, creds: Credentials, user: User) -> Credentials:
        """Refresh the credentials synchronously (called inside asyncio.to_thread)."""
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise GCalAuthError(
                "Google token refresh failed — user must re-authorise"
            ) from exc
        return creds

    async def _get_valid_credentials(self, user: User) -> Credentials:
        """Return valid, refreshed credentials; persist new tokens to DB if refreshed."""
        creds = self._get_credentials(user)
        if creds.expired and creds.refresh_token:
            creds = await asyncio.to_thread(self._refresh_credentials, creds, user)
            # Persist refreshed tokens
            user.google_access_token = creds.token
            if creds.expiry:
                user.google_token_expiry = creds.expiry.replace(tzinfo=timezone.utc)
            if self._db is not None:
                await self._db.flush()
        return creds

    def _build_service(self, creds: Credentials):  # type: ignore[return]
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    # ── Core operations ────────────────────────────────────────────────────────

    async def get_free_busy(
        self,
        user: User,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
    ) -> list[BusySlot]:
        """Return busy time ranges from Google Calendar."""
        creds = await self._get_valid_credentials(user)
        cal_id = user.preferences.get("calendar_id", calendar_id)

        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": cal_id}],
        }

        def _call() -> dict:
            service = self._build_service(creds)
            return service.freebusy().query(body=body).execute()

        try:
            result: dict = await asyncio.to_thread(_call)
        except HttpError as exc:
            self._handle_http_error(exc)

        busy_slots: list[BusySlot] = []
        for busy in result.get("calendars", {}).get(cal_id, {}).get("busy", []):
            busy_slots.append(
                BusySlot(
                    start=datetime.fromisoformat(busy["start"]),
                    end=datetime.fromisoformat(busy["end"]),
                )
            )
        return busy_slots

    async def create_event(
        self,
        user: User,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
        task_id: str | None = None,
        calendar_id: str = "primary",
    ) -> str:
        """Create a calendar event and return the event ID."""
        creds = await self._get_valid_credentials(user)
        tz = user.preferences.get("timezone", "Australia/Melbourne")
        cal_id = user.preferences.get("calendar_id", calendar_id)

        event_body: dict = {
            "summary": summary,
            "start": {"dateTime": start.isoformat(), "timeZone": tz},
            "end": {"dateTime": end.isoformat(), "timeZone": tz},
            "extendedProperties": {
                "private": {"kairos_managed": "true"},
            },
        }
        if description:
            event_body["description"] = description
        if task_id:
            event_body["extendedProperties"]["private"]["kairos_task_id"] = task_id

        def _call() -> dict:
            service = self._build_service(creds)
            return service.events().insert(calendarId=cal_id, body=event_body).execute()

        try:
            created: dict = await asyncio.to_thread(_call)
        except HttpError as exc:
            self._handle_http_error(exc)

        return created["id"]

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
        """Update an existing Kairos-managed calendar event (partial update)."""
        creds = await self._get_valid_credentials(user)
        tz = user.preferences.get("timezone", "Australia/Melbourne")
        cal_id = user.preferences.get("calendar_id", calendar_id)

        patch_body: dict = {}
        if summary is not None:
            patch_body["summary"] = summary
        if start is not None:
            patch_body["start"] = {"dateTime": start.isoformat(), "timeZone": tz}
        if end is not None:
            patch_body["end"] = {"dateTime": end.isoformat(), "timeZone": tz}
        if description is not None:
            patch_body["description"] = description

        if not patch_body:
            return

        def _call() -> None:
            service = self._build_service(creds)
            service.events().patch(
                calendarId=cal_id, eventId=event_id, body=patch_body
            ).execute()

        try:
            await asyncio.to_thread(_call)
        except HttpError as exc:
            self._handle_http_error(exc)

    async def delete_event(
        self,
        user: User,
        event_id: str,
        calendar_id: str = "primary",
    ) -> None:
        """Delete a Kairos-managed calendar event."""
        creds = await self._get_valid_credentials(user)
        cal_id = user.preferences.get("calendar_id", calendar_id)

        def _call() -> None:
            service = self._build_service(creds)
            service.events().delete(calendarId=cal_id, eventId=event_id).execute()

        try:
            await asyncio.to_thread(_call)
        except HttpError as exc:
            if exc.resp.status == 404:
                return  # Already deleted — treat as success
            self._handle_http_error(exc)

    async def get_events(
        self,
        user: User,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
    ) -> list[GCalEvent]:
        """List all events in a time range."""
        creds = await self._get_valid_credentials(user)
        cal_id = user.preferences.get("calendar_id", calendar_id)

        def _call() -> dict:
            service = self._build_service(creds)
            return (
                service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

        try:
            result: dict = await asyncio.to_thread(_call)
        except HttpError as exc:
            self._handle_http_error(exc)

        events: list[GCalEvent] = []
        for item in result.get("items", []):
            start_raw = item.get("start", {})
            end_raw = item.get("end", {})
            # Skip all-day events (no dateTime)
            if "dateTime" not in start_raw:
                continue
            private = (
                item.get("extendedProperties", {}).get("private", {})
            )
            events.append(
                GCalEvent(
                    id=item["id"],
                    summary=item.get("summary", ""),
                    start=datetime.fromisoformat(start_raw["dateTime"]),
                    end=datetime.fromisoformat(end_raw["dateTime"]),
                    description=item.get("description"),
                    kairos_task_id=private.get("kairos_task_id"),
                )
            )
        return events

    # ── Error handling ─────────────────────────────────────────────────────────

    def _handle_http_error(self, exc: HttpError) -> None:
        status = exc.resp.status
        if status in (401, 403):
            raise GCalAuthError(
                f"Google Calendar auth error ({status}) — user may need to re-authorise"
            ) from exc
        raise exc
