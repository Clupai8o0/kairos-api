# Kairos Scheduling Engine

The scheduling engine is the core value of Kairos. It reads tasks from the DB,
reads free/busy from Google Calendar, and slots tasks into available time.

---

## Table of Contents
1. [Scheduling Algorithm Overview](#algorithm-overview)
2. [Priority & Scoring](#priority-scoring)
3. [Slot Selection](#slot-selection)
4. [Task Splitting](#task-splitting)
5. [Dependency Resolution](#dependency-resolution)
6. [Conflict Handling](#conflict-handling)
7. [Buffer Time](#buffer-time)
8. [Blackout Days](#blackout-days)
9. [Rescheduling Strategy](#rescheduling-strategy)
10. [Edge Cases](#edge-cases)

---

## Algorithm Overview

The scheduler runs as a service function, not a standalone process. It can be triggered by:
1. **Task creation** (schedule-on-write) — schedules just the new task
2. **Task update** (if scheduling-relevant fields changed) — reschedules that task
3. **Manual trigger** (`POST /schedule/run`) — reschedules all or specified tasks
4. **(Future) Cron job** — nightly reschedule to optimise for the next day

### High-Level Flow

```
1. Collect schedulable tasks (pending + optionally scheduled tasks to optimise)
2. Sort by urgency score (see Priority & Scoring)
3. Fetch free/busy from Google Calendar for the scheduling horizon
4. Fetch blackout days from DB
5. Subtract blackout days and non-work-hours from available slots
6. For each task (highest urgency first):
   a. Check dependencies — skip if unmet
   b. Find best available slot (see Slot Selection)
   c. If splittable and no single slot fits, split into chunks
   d. Write event to Google Calendar
   e. Update task: scheduled_at, scheduled_end, gcal_event_id, status=scheduled
   f. Log the decision to schedule_logs
7. Return summary of scheduled, failed, unchanged
```

---

## Priority & Scoring

Each task gets an **urgency score** that determines scheduling order.
Higher score = scheduled first = gets the best time slots.

```python
def calculate_urgency(task: Task, now: datetime) -> float:
    score = 0.0

    # Priority weight (primary factor)
    priority_weights = {1: 100, 2: 60, 3: 30, 4: 10}
    score += priority_weights.get(task.priority, 30)

    # Deadline pressure (increases as deadline approaches)
    if task.deadline:
        hours_until_deadline = (task.deadline - now).total_seconds() / 3600
        if hours_until_deadline <= 0:
            score += 200  # OVERDUE — highest urgency
        elif hours_until_deadline <= 24:
            score += 150  # Due within 24h
        elif hours_until_deadline <= 72:
            score += 80   # Due within 3 days
        elif hours_until_deadline <= 168:
            score += 40   # Due within 1 week
        else:
            score += 10

    # Duration factor: shorter tasks get a small bonus (easier to slot)
    if task.duration_mins and task.duration_mins <= 30:
        score += 5

    return score
```

### Tie-Breaking

If two tasks have the same urgency score:
1. Earlier deadline wins
2. Earlier created_at wins
3. Alphabetical title (deterministic fallback)

---

## Slot Selection

The scheduler picks the **earliest available slot** that fits the task duration + buffer.

### Rules

1. **Work hours only** — respect `user.preferences.work_hours` (default 09:00–17:00)
2. **Buffer time** — subtract `task.buffer_mins` from slot availability (buffer after each task)
3. **Minimum slot size** — don't slot a 60min task into a 65min gap (too tight). Minimum gap
   should be `duration + buffer + 5min` to avoid back-to-back pressure.
4. **Earliest fit** — among valid slots, pick the earliest one. This front-loads the schedule
   and preserves afternoon flexibility.
5. **Deadline respect** — never schedule a task to start after its deadline minus its duration.

### Slot Finding Algorithm

```python
async def find_best_slot(
    task: Task,
    free_slots: list[TimeSlot],
    user_prefs: dict,
) -> TimeSlot | None:
    required_mins = task.duration_mins + task.buffer_mins

    for slot in free_slots:  # already sorted by start time
        # Check slot is within work hours
        if not is_within_work_hours(slot, user_prefs):
            continue

        # Check slot is before deadline
        if task.deadline:
            latest_start = task.deadline - timedelta(minutes=task.duration_mins)
            if slot.start > latest_start:
                return None  # No valid slots — all remaining are after deadline

        # Check slot is big enough
        if slot.duration_mins >= required_mins:
            return TimeSlot(
                start=slot.start,
                end=slot.start + timedelta(minutes=task.duration_mins),
            )

    return None  # No slot found
```

---

## Task Splitting

When `is_splittable=True` and `min_chunk_mins` is set, the scheduler can break a task
into multiple calendar blocks.

### Rules

1. Each chunk must be >= `min_chunk_mins`
2. Total chunk duration must equal `duration_mins`
3. Chunks are created as separate GCal events with linked titles
   (e.g., "Review report (1/3)", "Review report (2/3)", "Review report (3/3)")
4. The task's `gcal_event_id` stores a JSON array of event IDs
5. `scheduled_at` = start of first chunk, `scheduled_end` = end of last chunk

### Splitting Algorithm

```python
def split_task(task: Task, free_slots: list[TimeSlot]) -> list[TimeSlot] | None:
    remaining_mins = task.duration_mins
    chunks = []

    for slot in free_slots:
        if remaining_mins <= 0:
            break

        available = min(slot.duration_mins - task.buffer_mins, remaining_mins)
        if available >= task.min_chunk_mins:
            chunks.append(TimeSlot(start=slot.start, end=slot.start + timedelta(minutes=available)))
            remaining_mins -= available

    if remaining_mins > 0:
        return None  # Couldn't fit all chunks

    return chunks
```

---

## Dependency Resolution

Before scheduling a task, check `depends_on`:

```python
def can_schedule(task: Task, all_tasks: dict[str, Task]) -> bool:
    for dep_id in task.depends_on:
        dep = all_tasks.get(dep_id)
        if not dep or dep.status != TaskStatus.DONE:
            return False
    return True
```

Tasks with unmet dependencies are **skipped** (not failed). They'll be picked up on the
next scheduling run after their dependencies are completed.

---

## Conflict Handling

Conflicts happen when GCal state changes between the time we read free/busy and write events.

### Strategy

1. **Optimistic write**: Write the event. If GCal returns a conflict error, catch it.
2. **Retry with fresh data**: Re-fetch free/busy, try the next available slot.
3. **Max 3 retries per task**: After 3 failed attempts, mark as `failed` in the response.
4. **Never overwrite existing events**: Kairos only writes to empty slots.

---

## Buffer Time

Buffer is added **after** each scheduled task. Purpose: transition time between activities.

- Default: 15 minutes (from `user.preferences.buffer_mins`)
- Per-task override: `task.buffer_mins`
- Buffer is not a GCal event — it's consumed from the free slot
- A 60min task with 15min buffer needs a 75min slot

---

## Blackout Days

On blackout days, the scheduler treats the entire day as unavailable.

```python
async def get_available_days(user_id: str, start: date, end: date) -> list[date]:
    blackout_dates = await get_blackout_dates(user_id, start, end)
    all_dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return [d for d in all_dates if d not in blackout_dates]
    # All days of the week are considered. Use blackout days to block weekends if needed.
```

---

## Rescheduling Strategy

When `POST /schedule/run` is called for all tasks:

1. **Old events are always deleted first.** If a task already has a `gcal_event_id`, the
   existing GCal event(s) are deleted before a new one is created. This prevents orphaned
   calendar events accumulating across reschedule runs.
2. **Don't move tasks that are already well-placed.** If a task is scheduled and its slot
   is still valid (no conflict, before deadline), keep it unless a significantly better
   slot opened up. "Significantly better" = 2+ hours earlier.
3. **Unscheduled tasks get priority.** Process unscheduled tasks before considering
   rescheduling already-scheduled ones.
4. **Cancelled GCal events mean unscheduled.** If someone deletes a Kairos event from GCal
   directly, the next schedule run should detect the missing event and re-slot the task.

---

## Edge Cases

| Scenario | Behaviour |
|----------|-----------|
| Task has no duration | Skip scheduling, keep in backlog |
| Task deadline is in the past | Schedule ASAP (highest urgency), flag as overdue |
| No free slots within deadline | Return as `failed` with reason |
| No free slots at all | Return as `failed` with "no availability in horizon" |
| GCal API is down | Create task in DB, set scheduled_at=null, retry later |
| Task depends on cancelled task | Skip with reason "dependency cancelled" |
| All day blocked (blackout) | Skip that day entirely |
| Task longer than any single slot | If splittable, split. If not, fail with "no slot large enough" |
| User has no work hours set | Use default 09:00-17:00 AEST |