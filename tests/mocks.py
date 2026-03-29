"""Test mocks — MockGCalService and other shared test doubles."""

from dataclasses import dataclass, field
from datetime import datetime

from kairos.services.gcal_service import BusySlot


@dataclass
class MockGCalService:
    """In-memory stand-in for GCalService. No real API calls."""

    events: dict[str, dict] = field(default_factory=dict)
    busy_slots: list[BusySlot] = field(default_factory=list)

    async def get_free_busy(self, user, time_min, time_max, **kwargs) -> list[BusySlot]:
        return [
            s for s in self.busy_slots
            if s.end > time_min and s.start < time_max
        ]

    async def create_event(self, user, summary, start, end, **kwargs) -> str:
        event_id = f"mock_evt_{len(self.events)}"
        self.events[event_id] = {"summary": summary, "start": start, "end": end}
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

    def add_busy_slot(self, start: datetime, end: datetime) -> None:
        """Test helper — simulate an existing calendar event as a busy block."""
        self.busy_slots.append(BusySlot(start=start, end=end))
