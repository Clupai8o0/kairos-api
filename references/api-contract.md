# Kairos API Contract

Base URL: `http://localhost:8000/api/v1`

All endpoints require authentication (Bearer token or API key).
All request/response bodies are JSON.
All dates are ISO 8601 UTC.

---

## Table of Contents
1. [Auth](#auth)
2. [Tasks](#tasks)
3. [Projects](#projects)
4. [Tags](#tags)
5. [Views](#views)
6. [Schedule](#schedule)
7. [Calendar](#calendar)
8. [Blackout Days](#blackout-days)
9. [Health](#health)

---

## Auth

### `GET /auth/google/login`
Initiates Google OAuth flow. Redirects to Google consent screen.
Scopes requested: `openid email profile https://www.googleapis.com/auth/calendar`

### `GET /auth/google/callback`
Handles OAuth callback. Creates or updates user, sets JWT as an httpOnly cookie,
then redirects browser clients to `FRONTEND_URL` (default `http://localhost:3000/`).

**Response 302:**
- `Location: FRONTEND_URL`
- `Set-Cookie: access_token=...; HttpOnly; Path=/; SameSite=Lax`

### `POST /auth/api-key`
Generate an API key for agent/OpenClaw access.

**Response 200:**
```json
{
  "api_key": "kairos_sk_xxx",
  "created_at": "2026-03-29T00:00:00Z"
}
```

---

## Tasks

### `POST /tasks`
Create a task. Triggers auto-scheduling if `duration_mins` and `schedulable=true`.

**Request:**
```json
{
  "title": "Review PR #42",
  "description": "Check the auth refactor",
  "duration_mins": 30,
  "deadline": "2026-04-01T17:00:00Z",
  "priority": 2,
  "project_id": "cuid_xxx",
  "tag_ids": ["cuid_tag1", "cuid_tag2"],
  "is_splittable": false,
  "min_chunk_mins": null,
  "depends_on": [],
  "schedulable": true,
  "buffer_mins": 15,
  "metadata": {}
}
```
Only `title` is required. All other fields have defaults.

**Response 201:**
```json
{
  "id": "cuid_xxx",
  "title": "Review PR #42",
  "status": "scheduled",
  "scheduled_at": "2026-03-30T10:00:00Z",
  "scheduled_end": "2026-03-30T10:30:00Z",
  "gcal_event_id": "google_event_xxx",
  "tags": [{"id": "cuid_tag1", "name": "area:work", "color": "#2563EB"}],
  "...": "all task fields"
}
```

### `GET /tasks`
List tasks with filters.

**Query params:**
- `status` — comma-separated: `pending,scheduled,done`
- `priority` — comma-separated: `1,2`
- `project_id` — filter by project
- `tag_ids` — comma-separated tag IDs (AND logic)
- `is_scheduled` — `true` / `false`
- `due_before` — ISO date
- `due_after` — ISO date
- `search` — title/description keyword search
- `sort` — `priority`, `deadline`, `created_at`, `scheduled_at`
- `order` — `asc`, `desc`
- `limit` — default 50, max 200
- `offset` — pagination offset

**Response 200:**
```json
{
  "tasks": [...],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

### `GET /tasks/:id`
Single task with all fields including tags and project.

### `PATCH /tasks/:id`
Update any field(s). Triggers re-scheduling if duration/deadline/priority changed.

**Request:** Partial update — only include fields to change.
```json
{
  "priority": 1,
  "deadline": "2026-03-31T12:00:00Z"
}
```

### `DELETE /tasks/:id`
Soft delete: sets `status = "cancelled"`. Removes GCal event if scheduled.

### `POST /tasks/:id/complete`
Mark task as done. Sets `status = "done"`, `completed_at = now()`.
Removes GCal event (the time block is no longer needed).

### `POST /tasks/:id/unschedule`
Remove from calendar without deleting. Sets `status = "pending"`,
clears `scheduled_at`, `gcal_event_id`.

---

## Projects

### `POST /projects`
```json
{
  "title": "Kairos Backend",
  "description": "Build the scheduling API",
  "deadline": "2026-05-01T00:00:00Z",
  "color": "#10B981",
  "tag_ids": ["cuid_tag1"],
  "metadata": {}
}
```

### `GET /projects`
List all projects. Supports `status` filter.

### `GET /projects/:id`
Project with nested task list (summary: id, title, status, priority, scheduled_at).

### `PATCH /projects/:id`
Partial update.

### `DELETE /projects/:id`
Soft delete: sets `status = "archived"`. Does NOT cascade to tasks —
tasks remain but lose their project association.

### `GET /projects/:id/tasks`
All tasks for a project. Same filter/sort params as `GET /tasks`.

---

## Tags

### `POST /tags`
```json
{
  "name": "area:work",
  "color": "#2563EB",
  "icon": "briefcase"
}
```

### `GET /tags`
All tags for the user. Returns usage counts.
```json
{
  "tags": [
    {"id": "xxx", "name": "area:work", "color": "#2563EB", "icon": "briefcase", "task_count": 12, "project_count": 2}
  ]
}
```

### `PATCH /tags/:id`
Update name, color, or icon.

### `DELETE /tags/:id`
Hard delete. Removes tag from all task/project associations.

---

## Views

### `POST /views`
```json
{
  "name": "Deep Work This Week",
  "icon": "brain",
  "filter_config": {
    "tags_include": ["type:deep-work"],
    "due_within_days": 7,
    "status": ["pending", "scheduled"]
  },
  "sort_config": {
    "field": "priority",
    "direction": "asc"
  }
}
```

### `GET /views`
All views, ordered by `position`.

### `GET /views/:id`
View metadata (filter + sort config).

### `GET /views/:id/tasks`
Execute the view's filter and return matching tasks.
Same response shape as `GET /tasks`.

### `PATCH /views/:id`
Update filter, sort, name, icon, or position.

### `DELETE /views/:id`
Hard delete.

---

## Schedule

### `POST /schedule/run`
Trigger full reschedule for all pending/scheduled tasks.
Returns a summary of what changed.

**Request (optional):**
```json
{
  "task_ids": ["cuid_xxx"],
  "calendar_ids": ["primary", "work"],
  "horizon_days": 14,
  "dry_run": false
}
```
- `task_ids`: if provided, only reschedule these tasks. If omitted, reschedule all.
- `calendar_ids`: optional list of calendar IDs to include when computing busy windows.
- `horizon_days`: how far ahead to look for free slots. Default from user preferences.
- `dry_run`: if true, return what would change without writing to GCal.

**Response 200:**
```json
{
  "scheduled": [
    {"task_id": "xxx", "title": "Review PR", "scheduled_at": "2026-03-30T10:00:00Z", "scheduled_end": "2026-03-30T10:30:00Z"}
  ],
  "failed": [
    {"task_id": "yyy", "title": "Big report", "reason": "No free slot within deadline"}
  ],
  "unchanged": 12,
  "total_processed": 15
}
```

### `GET /schedule/today`
Today's schedule in user timezone, merged tasks + Google events across all linked
accounts and selected calendars, ordered by time.

Optional query params:
- `day` — `YYYY-MM-DD` in user timezone. Defaults to today.
- `task_events` — `exclude` (default) or `include`.
  - `exclude`: hide task-backed calendar events (task items remain visible).
  - `include`: return task-backed calendar events, flagged in payload.
- `calendar_ids` — comma-separated calendar IDs to include for this view.

Behavior note:
- Task items are always returned when scheduled.
- Calendar event items expose task linkage via `is_task_event` + `task_id`.

**Response 200:**
```json
{
  "date": "2026-03-29",
  "items": [
    {
      "type": "task",
      "task": {"id": "xxx", "title": "...", "scheduled_at": "...", "scheduled_end": "..."},
      "gcal_event_id": "google_xxx"
    },
    {
      "type": "event",
      "gcal_event": {"id": "google_yyy", "summary": "Team standup", "start": "...", "end": "..."}
    }
  ]
}
```

`gcal_event` includes:
- `event_id`
- `provider` (`google`)
- `account_id`
- `calendar_id`
- `calendar_name`
- `summary`
- `description`
- `location`
- `start`
- `end`
- `timezone`
- `is_all_day`
- `is_recurring_instance`
- `recurring_event_id` (optional)
- `html_link`
- `can_edit`
- `etag`
- `is_task_event`
- `task_id`

All-day event semantics:
- `is_all_day=true` when Google returns `start.date`/`end.date`
- `end` is exclusive for all-day events (Google Calendar behavior)

### `GET /schedule/week`
Same item contract as `GET /schedule/today`, grouped by day.

Optional query params:
- `start_date` — `YYYY-MM-DD` in user timezone. Defaults to current week's Monday.
- `end_date` — `YYYY-MM-DD` exclusive in user timezone. Defaults to `start_date + 7 days`.
- `task_events` — `exclude` (default) or `include`.
- `calendar_ids` — comma-separated calendar IDs to include for this view.

Behavior note:
- Task items are always returned when scheduled.
- Calendar event items expose task linkage via `is_task_event` + `task_id`.

### `GET /schedule/free-slots`
Return available time slots within a date range.

**Query params:**
- `start` — ISO date (required)
- `end` — ISO date (required)
- `min_duration_mins` — minimum slot size, default 30
- `calendar_ids` — optional comma-separated calendar IDs to include when computing busy windows

**Response 200:**
```json
{
  "slots": [
    {"start": "2026-03-30T10:00:00Z", "end": "2026-03-30T12:00:00Z", "duration_mins": 120},
    {"start": "2026-03-30T14:00:00Z", "end": "2026-03-30T17:00:00Z", "duration_mins": 180}
  ]
}
```

---

## Calendar

### `GET /calendar/accounts`
List linked Google accounts and discovered calendars.

Returns writable/read-only flags per calendar:
- `access_role` — Google role (`owner`, `writer`, `reader`, ...)
- `can_edit` — derived boolean used by frontend
- `selected` — persisted per-user schedule visibility preference

### `PATCH /calendar/accounts/selection`
Persist per-user calendar visibility preferences.

Request body:
```json
{
  "selections": [
    {"account_id": "acct_123", "calendar_id": "primary", "selected": false}
  ]
}
```

Response body:
```json
{
  "updated": 1,
  "accounts": [
    {
      "account_id": "acct_123",
      "email": "sam@test.com",
      "calendars": [
        {
          "calendar_id": "primary",
          "calendar_name": "Primary",
          "timezone": "Australia/Melbourne",
          "access_role": "owner",
          "can_edit": true,
          "selected": false,
          "is_primary": true
        }
      ]
    }
  ]
}
```

Rules:
- Idempotent: setting the current value returns `updated: 0`
- Unknown `account_id`/`calendar_id` pair returns `422` with `unknown_calendar_selection`
- Preferences persist across refreshes/sessions and provider sync

### `GET /calendar/events/:event_id?account_id=...&calendar_id=...`
Fetch event detail for edit prefill.

### `PATCH /calendar/events/:event_id`
Update a Google event.

Request body:
```json
{
  "account_id": "acct_123",
  "calendar_id": "primary",
  "etag": "\"3356021301328000\"",
  "mode": "single",
  "summary": "Updated title",
  "description": "Updated notes",
  "location": "Room 2",
  "start": "2026-04-01T09:30:00Z",
  "end": "2026-04-01T10:30:00Z",
  "timezone": "Australia/Melbourne"
}
```

`mode` values:
- `single` — update only the selected instance/event
- `series` — for recurring instances, updates the parent recurring event

All-day editing behavior:
- For all-day target events, backend writes `start.date` and `end.date` values.
- For timed events, backend writes `start.dateTime` and `end.dateTime` values.

Error codes:
- `google_auth_required` (401)
- `calendar_read_scope_missing` (403)
- `calendar_write_scope_missing` (403)
- `calendar_ownership_mismatch` (403)
- `calendar_read_only` (403)
- `calendar_event_not_found` (404)
- `calendar_event_etag_mismatch` (409)
- `invalid_timezone` (422)
- `invalid_date_range` (422)

## Blackout Days

### `POST /blackout-days`
```json
{
  "date": "2026-04-05",
  "reason": "Mental health day"
}
```

### `GET /blackout-days`
List all blackout days. Supports `after` and `before` date filters.

### `DELETE /blackout-days/:id`
Remove a blackout day.

---

## Health

### `GET /health`
```json
{
  "status": "ok",
  "version": "0.1.0",
  "db": "connected",
  "gcal": "connected"
}
```