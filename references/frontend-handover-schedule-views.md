# Frontend Handover: Schedule Views, Task/Event Separation, and Calendar Selection

## Goal

Render schedule timelines without duplicate task cards while preserving separate editing flows:
- Task editing uses task items (`type=task`)
- Event editing uses calendar event items (`type=event`)

## What Changed

### 1. Task-backed event handling in schedule views

Endpoints:
- `GET /api/v1/schedule/today`
- `GET /api/v1/schedule/week`

New query option:
- `task_events=exclude|include`
  - `exclude` (default): hide Google event rows that are backed by Kairos tasks
  - `include`: include all Google event rows, including task-backed events

Event payload additions (`item.type == "event"`):
- `is_task_event: boolean`
- `task_id: string | null`

Recommended frontend behavior:
- Default timeline call with `task_events=exclude`
- Render tasks from `type=task` rows
- Render non-task calendar blocks from `type=event` rows
- If you need a debug/admin timeline, call with `task_events=include` and use `is_task_event` to style/filter

---

### 2. Calendar scoping in schedule views

Both schedule view endpoints now accept:
- `calendar_ids=<comma,separated,ids>`

Behavior:
- If omitted: backend uses calendars selected by the user in calendar settings
- If provided: backend restricts event rows to those calendar IDs

Use case:
- Build custom schedule views (for example, Work-only, Personal-only) without changing global selection

---

### 3. Calendar scoping in scheduling/free-slot computation

Endpoints:
- `POST /api/v1/schedule/run`
- `GET /api/v1/schedule/free-slots`

New options:
- `POST /schedule/run` body: `calendar_ids: string[] | null`
- `GET /schedule/free-slots` query: `calendar_ids=<comma,separated,ids>`

Behavior:
- If omitted: scheduler uses selected calendars across linked accounts
- If provided: scheduler/free-slot computation uses only the provided calendars

Use case:
- Run targeted scheduling passes against a subset of calendars

---

## Existing Calendar Selection API (Persistent Preferences)

Endpoint:
- `PATCH /api/v1/calendar/accounts/selection`

Use this to persist global calendar inclusion/exclusion per account/calendar pair.
Selections are now respected by:
- Schedule event reads (today/week)
- Busy-time calculations for scheduling/free-slots

Example request:

```json
{
  "selections": [
    {"account_id": "acct_one", "calendar_id": "work", "selected": true},
    {"account_id": "acct_one", "calendar_id": "personal", "selected": false}
  ]
}
```

---

## Frontend Implementation Checklist

1. Timeline query defaults
- Use `task_events=exclude` by default for `today` and `week`.

2. Rendering model
- Render `type=task` rows as task cards.
- Render `type=event` rows as calendar cards.
- If `task_events=include`, hide or style task-backed event rows with `is_task_event`.

3. Calendar filters per view
- For temporary view-level filters, pass `calendar_ids` on schedule endpoints.
- For persistent settings, update `PATCH /calendar/accounts/selection`.

4. Scheduling runs
- Optional: include `calendar_ids` in `POST /schedule/run` when running focused scheduling modes.

5. Free slot panel
- Optional: pass `calendar_ids` to `GET /schedule/free-slots` to match active view filter.

---

## Example Calls

Today view, no duplicates:

```http
GET /api/v1/schedule/today?task_events=exclude
```

Today view, include and flag task-backed events:

```http
GET /api/v1/schedule/today?task_events=include
```

Week view, only work calendar:

```http
GET /api/v1/schedule/week?calendar_ids=work
```

Run scheduler using only work + shared calendars:

```http
POST /api/v1/schedule/run
Content-Type: application/json

{
  "task_ids": null,
  "calendar_ids": ["work", "shared"]
}
```

Free slots for selected subset:

```http
GET /api/v1/schedule/free-slots?days=7&calendar_ids=work,shared
```
