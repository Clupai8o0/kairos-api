"""Test mocks — MockGCalService and other shared test doubles."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from kairos.services.gcal_service import BusySlot


@dataclass
class MockGCalService:
    """In-memory stand-in for GCalService. No real API calls."""

    events: dict[str, dict] = field(default_factory=dict)
    busy_slots: list[BusySlot] = field(default_factory=list)
    account_calendars: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))

    def seed_calendar(
        self,
        *,
        account_id: str,
        account_email: str,
        calendar_id: str,
        calendar_name: str,
        access_role: str = "writer",
        selected: bool = True,
        is_free: bool = False,
        timezone: str | None = "UTC",
        is_primary: bool = False,
    ) -> None:
        self.account_calendars[account_id].append(
            {
                "account_id": account_id,
                "account_email": account_email,
                "calendar_id": calendar_id,
                "calendar_name": calendar_name,
                "access_role": access_role,
                "selected": selected,
                "is_free": is_free,
                "timezone": timezone,
                "is_primary": is_primary,
            }
        )

    async def get_free_busy(self, user, time_min, time_max, **kwargs) -> list[BusySlot]:
        return [
            s for s in self.busy_slots
            if s.end > time_min and s.start < time_max
        ]

    async def create_event(self, user, summary, start, end, **kwargs) -> str:
        event_id = f"mock_evt_{len(self.events)}"
        account_id = kwargs.get("account_id", "acct_primary")
        calendar_id = kwargs.get("calendar_id", "primary")
        self.events[event_id] = {
            "summary": summary,
            "start": start,
            "end": end,
            "description": kwargs.get("description"),
            "location": kwargs.get("location"),
            "account_id": account_id,
            "calendar_id": calendar_id,
            "calendar_name": kwargs.get("calendar_name", "Primary"),
            "etag": kwargs.get("etag", f"etag-{event_id}"),
            "is_all_day": kwargs.get("is_all_day", False),
            "is_recurring_instance": kwargs.get("is_recurring_instance", False),
            "recurring_event_id": kwargs.get("recurring_event_id"),
            "timezone": kwargs.get("timezone", "UTC"),
            "html_link": kwargs.get("html_link", f"https://calendar.google.com/event?eid={event_id}"),
            "task_id": kwargs.get("task_id"),
            "transparency": kwargs.get("transparency", "opaque"),
        }
        return event_id

    async def update_event(self, user, event_id, **kwargs) -> None:
        if event_id in self.events:
            self.events[event_id].update(
                {k: v for k, v in kwargs.items() if v is not None}
            )

    async def delete_event(self, user, event_id, **kwargs) -> None:
        self.events.pop(event_id, None)

    async def get_events(self, user, time_min, time_max, **kwargs) -> list[dict]:
        return [
            {**e, "id": eid}
            for eid, e in self.events.items()
            if e["end"] > time_min and e["start"] < time_max
        ]

    async def list_connected_calendars(self, user):
        info = []
        for account_id, calendars in self.account_calendars.items():
            for cal in calendars:
                info.append(
                    type(
                        "CalendarInfo",
                        (),
                        {
                            "account_id": account_id,
                            "account_email": cal["account_email"],
                            "calendar_id": cal["calendar_id"],
                            "calendar_name": cal["calendar_name"],
                            "timezone": cal["timezone"],
                            "access_role": cal["access_role"],
                            "selected": cal["selected"],
                            "is_free": cal.get("is_free", False),
                            "is_primary": cal["is_primary"],
                        },
                    )
                )
        return info

    async def update_calendar_selections(self, user, selections):
        updated = 0
        for selection in selections:
            account_id = selection["account_id"]
            calendar_id = selection["calendar_id"]
            target = None
            for cal in self.account_calendars.get(account_id, []):
                if cal["calendar_id"] == calendar_id:
                    target = cal
                    break
            if target is None:
                from kairos.services.gcal_service import GCalValidationError

                raise GCalValidationError(
                    "unknown_calendar_selection",
                    f"Unknown account/calendar pair: {account_id}/{calendar_id}",
                )
            selected = selection.get("selected")
            is_free = selection.get("is_free")

            if selected is None and is_free is None:
                from kairos.services.gcal_service import GCalValidationError

                raise GCalValidationError(
                    "invalid_calendar_selection_payload",
                    "At least one of selected or is_free must be provided",
                )

            if selected is not None and bool(target["selected"]) != bool(selected):
                target["selected"] = bool(selected)
                updated += 1

            if is_free is not None and bool(target.get("is_free", False)) != bool(is_free):
                target["is_free"] = bool(is_free)
                updated += 1
        return updated

    async def get_schedule_events(
        self,
        user,
        time_min,
        time_max,
        include_task_events=False,
        calendar_ids=None,
    ):
        events = []
        selected_pairs = {
            (cal["account_id"], cal["calendar_id"])
            for _, calendars in self.account_calendars.items()
            for cal in calendars
            if cal.get("selected", True)
        }
        include_calendar_ids = set(calendar_ids) if calendar_ids else None
        for event_id, event in self.events.items():
            if event["end"] <= time_min or event["start"] >= time_max:
                continue
            if include_calendar_ids is not None and event["calendar_id"] not in include_calendar_ids:
                continue
            if selected_pairs and (event["account_id"], event["calendar_id"]) not in selected_pairs:
                continue
            if event.get("task_id") and not include_task_events:
                continue
            events.append(
                type(
                    "ScheduleEvent",
                    (),
                    {
                        "event_id": event_id,
                        "provider": "google",
                        "account_id": event["account_id"],
                        "calendar_id": event["calendar_id"],
                        "calendar_name": event["calendar_name"],
                        "summary": event["summary"],
                        "description": event.get("description"),
                        "location": event.get("location"),
                        "start": event["start"],
                        "end": event["end"],
                        "timezone": event.get("timezone"),
                        "is_all_day": event.get("is_all_day", False),
                        "is_recurring_instance": event.get("is_recurring_instance", False),
                        "recurring_event_id": event.get("recurring_event_id"),
                        "html_link": event.get("html_link"),
                        "can_edit": event.get("can_edit", True),
                        "etag": event.get("etag"),
                        "is_task_event": bool(event.get("task_id")),
                        "task_id": event.get("task_id"),
                        "transparency": event.get("transparency", "opaque"),
                    },
                )
            )
        return sorted(events, key=lambda item: item.start)

    async def get_event_detail(self, user, event_id, account_id, calendar_id):
        event = self.events.get(event_id)
        if not event or event["account_id"] != account_id or event["calendar_id"] != calendar_id:
            from kairos.services.gcal_service import GCalNotFoundError

            raise GCalNotFoundError("calendar_event_not_found")
        details = await self.get_schedule_events(
            user,
            datetime.min.replace(tzinfo=ZoneInfo("UTC")),
            datetime.max.replace(tzinfo=ZoneInfo("UTC")),
        )
        for detail in details:
            if detail.event_id == event_id:
                return detail
        from kairos.services.gcal_service import GCalNotFoundError

        raise GCalNotFoundError("calendar_event_not_found")

    async def patch_event(
        self,
        user,
        event_id,
        account_id,
        calendar_id,
        **kwargs,
    ):
        from kairos.services.gcal_service import GCalConflictError, GCalNotFoundError, GCalPermissionError

        event = self.events.get(event_id)
        if not event:
            raise GCalNotFoundError("calendar_event_not_found")
        if event["account_id"] != account_id or event["calendar_id"] != calendar_id:
            raise GCalPermissionError("calendar_ownership_mismatch", "not owner")
        if event.get("can_edit") is False:
            raise GCalPermissionError("calendar_read_only", "calendar is read-only")
        provided_etag = kwargs.get("etag")
        if provided_etag and provided_etag != event.get("etag"):
            raise GCalConflictError("calendar_event_etag_mismatch")

        for field in ("summary", "description", "location", "start", "end", "transparency"):
            if kwargs.get(field) is not None:
                event[field] = kwargs[field]
        if kwargs.get("timezone_name") is not None:
            event["timezone"] = kwargs["timezone_name"]
        event["etag"] = f"etag-{event_id}-updated"

        details = await self.get_schedule_events(
            user,
            datetime.min.replace(tzinfo=ZoneInfo("UTC")),
            datetime.max.replace(tzinfo=ZoneInfo("UTC")),
        )
        for detail in details:
            if detail.event_id == event_id:
                return detail
        raise GCalNotFoundError("calendar_event_not_found")

    def add_busy_slot(self, start: datetime, end: datetime) -> None:
        """Test helper — simulate an existing calendar event as a busy block."""
        self.busy_slots.append(BusySlot(start=start, end=end))
