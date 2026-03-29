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
7. [Blackout Days](#blackout-days)
8. [Health](#health)

---

## Auth

### `GET /auth/google`
Initiates Google OAuth flow. Redirects to Google consent screen.
Scopes requested: `openid email profile https://www.googleapis.com/auth/calendar`

### `GET /auth/google/callback`
Handles OAuth callback. Creates or updates user. Returns JWT.

**Response 200:**
```json
{
  "access_token": "jwt_token_here",
  "token_type": "bearer",
  "user": {
    "id": "cuid_xxx",
    "email": "sam@example.com",
    "name": "Samridh Limbu"
  }
}
```

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
  "horizon_days": 14,
  "dry_run": false
}
```
- `task_ids`: if provided, only reschedule these tasks. If omitted, reschedule all.
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
Today's schedule: merged tasks + GCal events, ordered by time.

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

### `GET /schedule/week`
Same as today but for the current week (Mon-Sun).

### `GET /schedule/free-slots`
Return available time slots within a date range.

**Query params:**
- `start` — ISO date (required)
- `end` — ISO date (required)
- `min_duration_mins` — minimum slot size, default 30

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