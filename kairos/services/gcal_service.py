"""Google Calendar API wrapper — read free/busy, write events, delete events."""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.config import settings
from kairos.models.google_account import GoogleAccount
from kairos.models.google_calendar import GoogleCalendar
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
    is_all_day: bool = False


@dataclass
class GoogleCalendarInfo:
    account_id: str
    account_email: str
    calendar_id: str
    calendar_name: str
    timezone: str | None
    access_role: str
    selected: bool
    is_primary: bool


@dataclass
class GoogleScheduleEvent:
    event_id: str
    provider: str
    account_id: str
    calendar_id: str
    calendar_name: str
    summary: str
    description: str | None
    location: str | None
    start: datetime
    end: datetime
    timezone: str | None
    is_all_day: bool
    is_recurring_instance: bool
    recurring_event_id: str | None
    html_link: str | None
    can_edit: bool
    etag: str | None
    is_task_event: bool
    task_id: str | None


class GCalAuthError(Exception):
    """Raised when the user needs to re-authorise Google Calendar access."""


class GCalPermissionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GCalConflictError(Exception):
    pass


class GCalNotFoundError(Exception):
    pass


class GCalMissingScopeError(GCalPermissionError):
    pass


class GCalValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GCalService:
    """Async wrapper around Google Calendar API v3."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        # db is optional — only needed when token refresh requires persisting new tokens
        self._db = db

    _calendar_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
    _calendar_cache_ttl_seconds = 300
    _required_read_scopes = {
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.readonly",
    }
    _required_write_scopes = {
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
    }

    @staticmethod
    def _normalize_google_expiry(expiry: datetime | None) -> datetime | None:
        """Google creds expects naive UTC expiry for `expired` comparisons."""
        if expiry is None:
            return None
        if expiry.tzinfo is None:
            return expiry
        return expiry.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _parse_google_event_window(
        start_raw: dict[str, Any],
        end_raw: dict[str, Any],
    ) -> tuple[datetime, datetime, bool] | None:
        """Parse Google event start/end for timed and all-day events.

        All-day events use date-only values with an exclusive end date.
        """
        is_all_day = "date" in start_raw and "dateTime" not in start_raw
        try:
            if is_all_day:
                start = datetime.fromisoformat(f"{start_raw['date']}T00:00:00+00:00")
                end = datetime.fromisoformat(f"{end_raw['date']}T00:00:00+00:00")
            else:
                start = datetime.fromisoformat(start_raw["dateTime"])
                end = datetime.fromisoformat(end_raw["dateTime"])
        except (KeyError, ValueError):
            return None

        return start, end, is_all_day

    @staticmethod
    def _to_google_event_time(
        dt: datetime,
        *,
        is_all_day: bool,
        timezone_name: str,
    ) -> dict[str, str]:
        if is_all_day:
            return {"date": dt.date().isoformat()}
        return {"dateTime": dt.isoformat(), "timeZone": timezone_name}

    # ── Credentials ────────────────────────────────────────────────────────────

    def _get_credentials(self, user: User, account: GoogleAccount | None = None) -> Credentials:
        """Build credentials from user tokens, refreshing if expired."""
        token = account.access_token if account else user.google_access_token
        refresh = account.refresh_token if account else user.google_refresh_token
        expiry = account.token_expiry if account else user.google_token_expiry
        expiry = self._normalize_google_expiry(expiry)
        creds = Credentials(
            token=token,
            refresh_token=refresh,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            expiry=expiry,
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

    async def _get_valid_credentials(
        self, user: User, account: GoogleAccount | None = None
    ) -> Credentials:
        """Return valid, refreshed credentials; persist new tokens to DB if refreshed."""
        creds = self._get_credentials(user, account)
        if creds.expired and creds.refresh_token:
            creds = await asyncio.to_thread(self._refresh_credentials, creds, user)
            # Persist refreshed tokens
            if account is None:
                user.google_access_token = creds.token
                if creds.expiry:
                    user.google_token_expiry = creds.expiry.replace(tzinfo=timezone.utc)
            else:
                account.access_token = creds.token
                if creds.expiry:
                    account.token_expiry = creds.expiry.replace(tzinfo=timezone.utc)
            if self._db is not None:
                await self._db.flush()
        elif creds.expired and not creds.refresh_token:
            raise GCalAuthError("google_refresh_token_missing")
        return creds

    def _build_service(self, creds: Credentials):  # type: ignore[return]
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    async def _execute_with_retry(self, fn, retries: int = 3):
        attempt = 0
        while True:
            try:
                return await asyncio.to_thread(fn)
            except HttpError as exc:
                if exc.resp.status in (429, 500, 503) and attempt < retries - 1:
                    await asyncio.sleep(0.25 * (2 ** attempt))
                    attempt += 1
                    continue
                raise
            except OSError:
                if attempt < retries - 1:
                    await asyncio.sleep(0.25 * (2 ** attempt))
                    attempt += 1
                    continue
                raise

    async def _accounts_for_user(self, user: User) -> list[GoogleAccount]:
        if self._db is None:
            return []
        rows = await self._db.execute(
            select(GoogleAccount).where(GoogleAccount.user_id == user.id).order_by(GoogleAccount.created_at)
        )
        accounts = list(rows.scalars().all())
        if accounts:
            return accounts

        # Backfill a primary account row for users created before multi-account support.
        if user.google_id and user.google_access_token:
            account = GoogleAccount(
                user_id=user.id,
                google_account_id=user.google_id,
                email=user.email,
                display_name=user.name,
                access_token=user.google_access_token,
                refresh_token=user.google_refresh_token,
                token_expiry=user.google_token_expiry,
                scopes=["https://www.googleapis.com/auth/calendar"],
                is_primary=True,
            )
            self._db.add(account)
            await self._db.flush()
            accounts.append(account)
        return accounts

    def _validate_scope(self, account: GoogleAccount, write: bool = False) -> None:
        required = self._required_write_scopes if write else self._required_read_scopes
        granted = set(account.scopes or [])
        if not (required & granted):
            mode = "calendar_write_scope_missing" if write else "calendar_read_scope_missing"
            raise GCalMissingScopeError(mode, "Google Calendar scope missing; re-consent required")

    def _can_edit_calendar(self, calendar: GoogleCalendar) -> bool:
        return calendar.access_role in {"owner", "writer"}

    async def _sync_calendars_for_account(
        self, user: User, account: GoogleAccount
    ) -> list[GoogleCalendar]:
        if self._db is None:
            return []

        now_ts = time.time()
        cached = self._calendar_cache.get(account.id)
        if cached and (now_ts - cached[0]) < self._calendar_cache_ttl_seconds:
            items = cached[1]
        else:
            creds = await self._get_valid_credentials(user, account)

            def _call() -> dict:
                service = self._build_service(creds)
                return service.calendarList().list(showHidden=False).execute()

            try:
                result: dict = await self._execute_with_retry(_call)
            except HttpError as exc:
                self._handle_http_error(exc)

            items = result.get("items", [])
            self._calendar_cache[account.id] = (now_ts, items)

        rows = await self._db.execute(
            select(GoogleCalendar).where(GoogleCalendar.account_id == account.id)
        )
        existing = {
            c.google_calendar_id: c
            for c in rows.scalars().all()
        }

        synced: list[GoogleCalendar] = []
        for item in items:
            calendar_id = item.get("id")
            if not calendar_id:
                continue

            cal = existing.get(calendar_id)
            provider_selected = bool(item.get("selected", True))
            if cal is None:
                cal = GoogleCalendar(
                    account_id=account.id,
                    google_calendar_id=calendar_id,
                    name=item.get("summaryOverride") or item.get("summary") or calendar_id,
                    timezone=item.get("timeZone"),
                    access_role=item.get("accessRole", "reader"),
                    selected=provider_selected,
                    is_primary=bool(item.get("primary", False)),
                )
                self._db.add(cal)
            else:
                cal.name = item.get("summaryOverride") or item.get("summary") or cal.name
                cal.timezone = item.get("timeZone")
                cal.access_role = item.get("accessRole", cal.access_role)
                # Preserve user visibility preference once a calendar row exists.
                cal.is_primary = bool(item.get("primary", False))
            synced.append(cal)

        await self._db.flush()
        return synced

    async def list_connected_calendars(self, user: User) -> list[GoogleCalendarInfo]:
        accounts = await self._accounts_for_user(user)
        infos: list[GoogleCalendarInfo] = []
        for account in accounts:
            self._validate_scope(account, write=False)
            calendars = await self._sync_calendars_for_account(user, account)
            for cal in calendars:
                infos.append(
                    GoogleCalendarInfo(
                        account_id=account.id,
                        account_email=account.email,
                        calendar_id=cal.google_calendar_id,
                        calendar_name=cal.name,
                        timezone=cal.timezone,
                        access_role=cal.access_role,
                        selected=cal.selected,
                        is_primary=cal.is_primary,
                    )
                )
        return infos

    async def update_calendar_selections(
        self,
        user: User,
        selections: list[dict[str, Any]],
    ) -> int:
        if self._db is None:
            raise GCalValidationError("calendar_selection_unavailable", "No DB session bound")

        accounts = await self._accounts_for_user(user)
        account_ids = {account.id for account in accounts}

        # Refresh discovered calendars first so newly-connected calendars can be selected.
        for account in accounts:
            try:
                self._validate_scope(account, write=False)
                await self._sync_calendars_for_account(user, account)
            except GCalMissingScopeError:
                continue

        rows = await self._db.execute(
            select(GoogleCalendar, GoogleAccount)
            .join(GoogleAccount, GoogleCalendar.account_id == GoogleAccount.id)
            .where(GoogleAccount.user_id == user.id)
        )
        calendars_by_pair = {
            (account.id, cal.google_calendar_id): cal
            for cal, account in rows.all()
        }

        updated = 0
        for selection in selections:
            account_id = selection.get("account_id")
            calendar_id = selection.get("calendar_id")
            selected = bool(selection.get("selected"))

            if account_id not in account_ids:
                raise GCalValidationError(
                    "unknown_calendar_selection",
                    f"Unknown account/calendar pair: {account_id}/{calendar_id}",
                )

            cal = calendars_by_pair.get((account_id, calendar_id))
            if cal is None:
                raise GCalValidationError(
                    "unknown_calendar_selection",
                    f"Unknown account/calendar pair: {account_id}/{calendar_id}",
                )

            if cal.selected != selected:
                cal.selected = selected
                updated += 1

        await self._db.flush()
        return updated

    # ── Core operations ────────────────────────────────────────────────────────

    async def get_free_busy(
        self,
        user: User,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
        calendar_ids: set[str] | None = None,
    ) -> list[BusySlot]:
        """Return busy time ranges from Google Calendar."""
        accounts = await self._accounts_for_user(user)
        busy_slots: list[BusySlot] = []

        if accounts:
            queried_any = False
            for account in accounts:
                self._validate_scope(account, write=False)
                calendars = await self._sync_calendars_for_account(user, account)
                selected_calendar_ids = [
                    cal.google_calendar_id
                    for cal in calendars
                    if cal.selected and (calendar_ids is None or cal.google_calendar_id in calendar_ids)
                ]

                if not selected_calendar_ids:
                    continue

                queried_any = True
                creds = await self._get_valid_credentials(user, account)
                body = {
                    "timeMin": time_min.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "items": [{"id": cal_id} for cal_id in selected_calendar_ids],
                }

                def _call() -> dict:
                    service = self._build_service(creds)
                    return service.freebusy().query(body=body).execute()

                try:
                    result: dict = await self._execute_with_retry(_call)
                except HttpError as exc:
                    self._handle_http_error(exc)

                for cal_id in selected_calendar_ids:
                    for busy in result.get("calendars", {}).get(cal_id, {}).get("busy", []):
                        busy_slots.append(
                            BusySlot(
                                start=datetime.fromisoformat(busy["start"]),
                                end=datetime.fromisoformat(busy["end"]),
                            )
                        )

            if queried_any:
                return sorted(busy_slots, key=lambda slot: slot.start)

        creds = await self._get_valid_credentials(user)
        cal_id = user.preferences.get("calendar_id", calendar_id)
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": cal_id}],
        }

        def _fallback_call() -> dict:
            service = self._build_service(creds)
            return service.freebusy().query(body=body).execute()

        try:
            result = await self._execute_with_retry(_fallback_call)
        except HttpError as exc:
            self._handle_http_error(exc)

        for busy in result.get("calendars", {}).get(cal_id, {}).get("busy", []):
            busy_slots.append(
                BusySlot(
                    start=datetime.fromisoformat(busy["start"]),
                    end=datetime.fromisoformat(busy["end"]),
                )
            )
        return sorted(busy_slots, key=lambda slot: slot.start)

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
        accounts = await self._accounts_for_user(user)
        account = next((a for a in accounts if a.is_primary), accounts[0]) if accounts else None
        if account:
            self._validate_scope(account, write=True)
        creds = await self._get_valid_credentials(user, account)
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
            created: dict = await self._execute_with_retry(_call)
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
        accounts = await self._accounts_for_user(user)
        account = next((a for a in accounts if a.is_primary), accounts[0]) if accounts else None
        if account:
            self._validate_scope(account, write=True)
        creds = await self._get_valid_credentials(user, account)
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
            await self._execute_with_retry(_call)
        except HttpError as exc:
            self._handle_http_error(exc)

    async def delete_event(
        self,
        user: User,
        event_id: str,
        calendar_id: str = "primary",
    ) -> None:
        """Delete a Kairos-managed calendar event."""
        accounts = await self._accounts_for_user(user)
        account = next((a for a in accounts if a.is_primary), accounts[0]) if accounts else None
        if account:
            self._validate_scope(account, write=True)
        creds = await self._get_valid_credentials(user, account)
        cal_id = user.preferences.get("calendar_id", calendar_id)

        def _call() -> None:
            service = self._build_service(creds)
            service.events().delete(calendarId=cal_id, eventId=event_id).execute()

        try:
            await self._execute_with_retry(_call)
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
        accounts = await self._accounts_for_user(user)
        account = next((a for a in accounts if a.is_primary), accounts[0]) if accounts else None
        if account:
            self._validate_scope(account, write=False)
        creds = await self._get_valid_credentials(user, account)
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
            result: dict = await self._execute_with_retry(_call)
        except HttpError as exc:
            self._handle_http_error(exc)

        events: list[GCalEvent] = []
        for item in result.get("items", []):
            start_raw = item.get("start", {})
            end_raw = item.get("end", {})
            parsed = self._parse_google_event_window(start_raw, end_raw)
            if parsed is None:
                continue
            start, end, is_all_day = parsed
            private = (
                item.get("extendedProperties", {}).get("private", {})
            )
            events.append(
                GCalEvent(
                    id=item["id"],
                    summary=item.get("summary", ""),
                    start=start,
                    end=end,
                    description=item.get("description"),
                    kairos_task_id=private.get("kairos_task_id"),
                    is_all_day=is_all_day,
                )
            )
        return events

    async def get_schedule_events(
        self,
        user: User,
        time_min: datetime,
        time_max: datetime,
        include_task_events: bool = False,
        calendar_ids: set[str] | None = None,
    ) -> list[GoogleScheduleEvent]:
        accounts = await self._accounts_for_user(user)
        if not accounts:
            return []

        calendars_by_account: dict[str, list[GoogleCalendar]] = {}
        for account in accounts:
            self._validate_scope(account, write=False)
            calendars = await self._sync_calendars_for_account(user, account)
            calendars_by_account[account.id] = [
                c
                for c in calendars
                if c.selected and (calendar_ids is None or c.google_calendar_id in calendar_ids)
            ]

        sem = asyncio.Semaphore(6)

        async def _fetch(account: GoogleAccount, calendar: GoogleCalendar) -> list[GoogleScheduleEvent]:
            async with sem:
                creds = await self._get_valid_credentials(user, account)

                def _call() -> dict:
                    service = self._build_service(creds)
                    return (
                        service.events()
                        .list(
                            calendarId=calendar.google_calendar_id,
                            timeMin=time_min.isoformat(),
                            timeMax=time_max.isoformat(),
                            singleEvents=True,
                            orderBy="startTime",
                        )
                        .execute()
                    )

                try:
                    result: dict = await self._execute_with_retry(_call)
                except HttpError as exc:
                    self._handle_http_error(exc)

                mapped: list[GoogleScheduleEvent] = []
                for item in result.get("items", []):
                    event = self._map_schedule_event(account, calendar, item)
                    if event is not None:
                        if not include_task_events and event.is_task_event:
                            continue
                        mapped.append(event)
                return mapped

        tasks = [
            _fetch(account, calendar)
            for account in accounts
            for calendar in calendars_by_account.get(account.id, [])
        ]
        if not tasks:
            return []

        flattened: list[GoogleScheduleEvent] = []
        for events in await asyncio.gather(*tasks):
            flattened.extend(events)

        # Dedupe by stable identity: account + calendar + event_id + start
        deduped: dict[str, GoogleScheduleEvent] = {}
        for event in flattened:
            key = f"{event.account_id}:{event.calendar_id}:{event.event_id}:{event.start.isoformat()}"
            deduped[key] = event

        return sorted(deduped.values(), key=lambda e: e.start)

    def _map_schedule_event(
        self,
        account: GoogleAccount,
        calendar: GoogleCalendar,
        item: dict[str, Any],
    ) -> GoogleScheduleEvent | None:
        start_raw = item.get("start", {})
        end_raw = item.get("end", {})

        parsed = self._parse_google_event_window(start_raw, end_raw)
        if parsed is None:
            return None
        start, end, is_all_day = parsed

        can_edit = self._can_edit_calendar(calendar)
        private = item.get("extendedProperties", {}).get("private", {})
        task_id = private.get("kairos_task_id")
        return GoogleScheduleEvent(
            event_id=item.get("id", ""),
            provider="google",
            account_id=account.id,
            calendar_id=calendar.google_calendar_id,
            calendar_name=calendar.name,
            summary=item.get("summary") or "(No title)",
            description=item.get("description"),
            location=item.get("location"),
            start=start,
            end=end,
            timezone=start_raw.get("timeZone") or end_raw.get("timeZone") or calendar.timezone,
            is_all_day=is_all_day,
            is_recurring_instance=bool(item.get("recurringEventId")),
            recurring_event_id=item.get("recurringEventId"),
            html_link=item.get("htmlLink"),
            can_edit=can_edit,
            etag=item.get("etag"),
            is_task_event=bool(task_id),
            task_id=task_id,
        )

    async def get_event_detail(
        self,
        user: User,
        event_id: str,
        account_id: str,
        calendar_id: str,
    ) -> GoogleScheduleEvent:
        account, calendar = await self._owned_calendar(user, account_id, calendar_id)
        self._validate_scope(account, write=False)

        creds = await self._get_valid_credentials(user, account)

        def _call() -> dict:
            service = self._build_service(creds)
            return service.events().get(calendarId=calendar.google_calendar_id, eventId=event_id).execute()

        try:
            payload: dict = await self._execute_with_retry(_call)
        except HttpError as exc:
            if exc.resp.status == 404:
                raise GCalNotFoundError("calendar_event_not_found") from exc
            self._handle_http_error(exc)

        event = self._map_schedule_event(account, calendar, payload)
        if event is None:
            raise GCalNotFoundError("calendar_event_not_found")
        return event

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
        account, calendar = await self._owned_calendar(user, account_id, calendar_id)
        if not self._can_edit_calendar(calendar):
            raise GCalPermissionError("calendar_read_only", "Calendar is read-only")
        self._validate_scope(account, write=True)

        creds = await self._get_valid_credentials(user, account)

        def _get() -> dict:
            service = self._build_service(creds)
            return service.events().get(calendarId=calendar.google_calendar_id, eventId=event_id).execute()

        try:
            current: dict = await self._execute_with_retry(_get)
        except HttpError as exc:
            if exc.resp.status == 404:
                raise GCalNotFoundError("calendar_event_not_found") from exc
            self._handle_http_error(exc)

        if etag and current.get("etag") != etag:
            raise GCalConflictError("calendar_event_etag_mismatch")

        patch_body: dict[str, Any] = {}
        if summary is not None:
            patch_body["summary"] = summary
        if description is not None:
            patch_body["description"] = description
        if location is not None:
            patch_body["location"] = location

        active_tz = timezone_name or (
            current.get("start", {}).get("timeZone")
            or current.get("end", {}).get("timeZone")
            or calendar.timezone
            or "UTC"
        )
        is_all_day = "date" in current.get("start", {}) and "dateTime" not in current.get("start", {})

        if start is not None:
            patch_body["start"] = self._to_google_event_time(
                start,
                is_all_day=is_all_day,
                timezone_name=active_tz,
            )
        if end is not None:
            patch_body["end"] = self._to_google_event_time(
                end,
                is_all_day=is_all_day,
                timezone_name=active_tz,
            )

        target_event_id = event_id
        if mode == "series" and current.get("recurringEventId"):
            target_event_id = current["recurringEventId"]

        def _patch() -> dict:
            service = self._build_service(creds)
            return (
                service.events()
                .patch(
                    calendarId=calendar.google_calendar_id,
                    eventId=target_event_id,
                    body=patch_body,
                )
                .execute()
            )

        try:
            updated: dict = await self._execute_with_retry(_patch)
        except HttpError as exc:
            if exc.resp.status == 404:
                raise GCalNotFoundError("calendar_event_not_found") from exc
            self._handle_http_error(exc)

        mapped = self._map_schedule_event(account, calendar, updated)
        if mapped is None:
            raise GCalNotFoundError("calendar_event_not_found")
        return mapped

    async def _owned_calendar(
        self, user: User, account_id: str, calendar_id: str
    ) -> tuple[GoogleAccount, GoogleCalendar]:
        if self._db is None:
            raise GCalPermissionError("calendar_ownership_mismatch", "No DB session bound")

        account_row = await self._db.execute(
            select(GoogleAccount).where(
                GoogleAccount.id == account_id,
                GoogleAccount.user_id == user.id,
            )
        )
        account = account_row.scalar_one_or_none()
        if account is None:
            raise GCalPermissionError("calendar_ownership_mismatch", "Account is not linked")

        await self._sync_calendars_for_account(user, account)
        cal_row = await self._db.execute(
            select(GoogleCalendar).where(
                GoogleCalendar.account_id == account.id,
                GoogleCalendar.google_calendar_id == calendar_id,
            )
        )
        calendar = cal_row.scalar_one_or_none()
        if calendar is None:
            raise GCalPermissionError("calendar_ownership_mismatch", "Calendar is not linked")
        return account, calendar

    # ── Error handling ─────────────────────────────────────────────────────────

    def _handle_http_error(self, exc: HttpError) -> None:
        status = exc.resp.status
        if status in (401, 403):
            message = "google_token_invalid_or_revoked" if status == 401 else "google_forbidden"
            raise GCalAuthError(message) from exc
        if status == 409:
            raise GCalConflictError("calendar_event_conflict") from exc
        if status == 404:
            raise GCalNotFoundError("calendar_event_not_found") from exc
        raise exc
