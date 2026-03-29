# Kairos Data Model

## Table of Contents
1. [User](#user)
2. [Task](#task)
3. [Project](#project)
4. [Tag](#tag)
5. [TaskTag / ProjectTag](#junction-tables)
6. [View](#view)
7. [BlackoutDay](#blackoutday)
8. [ScheduleLog](#schedulelog)
9. [Relationships Diagram](#relationships)

---

## User

Single user for v1, but the model exists for future expansion.

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    google_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    # preferences schema:
    # {
    #   "work_hours": {"start": "09:00", "end": "17:00"},
    #   "buffer_mins": 15,
    #   "default_duration_mins": 60,
    #   "scheduling_horizon_days": 14,
    #   "calendar_id": "primary",
    #   "timezone": "Australia/Melbourne"
    # }
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

---

## Task

The core entity. Everything in Kairos revolves around tasks.

```python
class TaskStatus(str, Enum):
    PENDING = "pending"           # Not yet scheduled
    SCHEDULED = "scheduled"       # Has a gcal_event_id and scheduled_at
    IN_PROGRESS = "in_progress"   # User started working on it
    DONE = "done"                 # Completed
    CANCELLED = "cancelled"       # Soft-deleted

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)

    # Core fields
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_mins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Tasks without duration cannot be auto-scheduled — they stay in backlog

    # Scheduling fields
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)
    # 1 = critical (must do today/tomorrow)
    # 2 = high (this week)
    # 3 = normal (default)
    # 4 = low (whenever)
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.PENDING)
    schedulable: Mapped[bool] = mapped_column(Boolean, default=True)
    # False = manually pinned, never auto-moved

    # Google Calendar reference
    gcal_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Flexibility fields
    buffer_mins: Mapped[int] = mapped_column(Integer, default=15)
    min_chunk_mins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # If set, task can be split into chunks no smaller than this
    # e.g., a 2hr task with min_chunk=30 can become 4x30min blocks
    is_splittable: Mapped[bool] = mapped_column(Boolean, default=False)

    # Dependencies
    depends_on: Mapped[list] = mapped_column(ARRAY(String), default=list)
    # Array of task IDs that must be completed before this task can be scheduled

    # Flexible metadata (for future expansion)
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    # metadata can hold anything: estimated_energy, location, tools_needed, etc.

    # Timestamps
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="tasks")
    project: Mapped["Project"] = relationship(back_populates="tasks")
    tags: Mapped[list["Tag"]] = relationship(secondary="task_tags", back_populates="tasks")
```

### Key Design Notes

- **`duration_mins` is nullable**: Tasks without a duration are valid (e.g., "Review PR" where
  you don't know how long it'll take). They appear in the backlog but the scheduler skips them.
- **`is_splittable` + `min_chunk_mins`**: Enables breaking a 4-hour task into multiple blocks.
  The scheduler creates multiple GCal events and links them via metadata.
- **`depends_on`**: Simple array of task IDs. Scheduler checks all dependencies are `done`
  before scheduling. No complex DAG — just one-level blocking.
- **`metadata` (JSONB)**: The escape hatch. Anything that doesn't warrant a dedicated column
  goes here. Frontends and agents can write/read arbitrary keys without schema changes.
- **`schedulable`**: When false, the task is pinned — manual control. Useful for tasks the
  user explicitly placed at a specific time.

---

## Project

Flat container of tasks. No phases, no milestones.

```python
class ProjectStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ProjectStatus.ACTIVE)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # hex color
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project")
    tags: Mapped[list["Tag"]] = relationship(secondary="project_tags", back_populates="projects")
```

---

## Tag

Universal organiser. Replaces categories, contexts, areas, and types.

```python
class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # hex
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)  # emoji or icon name

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(secondary="task_tags", back_populates="tags")
    projects: Mapped[list["Project"]] = relationship(secondary="project_tags", back_populates="projects")

    # Unique constraint: one tag name per user
    __table_args__ = (UniqueConstraint("user_id", "name"),)
```

### Tag Naming Convention

Tags use namespace prefixes by convention (not enforced in schema):
- `area:work`, `area:personal`, `area:uni`
- `context:laptop`, `context:phone`, `context:home`
- `energy:high`, `energy:low`
- `type:deep-work`, `type:admin`, `type:meeting`

This enables powerful filtering without rigid schema categories.

---

## Junction Tables

```python
task_tags = Table(
    "task_tags", Base.metadata,
    Column("task_id", String, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", String, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

project_tags = Table(
    "project_tags", Base.metadata,
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", String, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)
```

---

## View

Saved filter configuration. Not materialised data.

```python
class View(Base):
    __tablename__ = "views"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)  # ordering in sidebar

    filter_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # filter_config schema:
    # {
    #   "tags_include": ["area:work"],         # must have ALL of these
    #   "tags_exclude": ["type:meeting"],       # must NOT have any of these
    #   "status": ["pending", "scheduled"],
    #   "priority": [1, 2],
    #   "project_id": "cuid_xxx",              # optional, filter by project
    #   "due_within_days": 7,                  # relative deadline filter
    #   "is_scheduled": false,                 # true/false/null (any)
    #   "search": "keyword"                    # title/description search
    # }

    sort_config: Mapped[dict] = mapped_column(JSONB, default=lambda: {"field": "priority", "direction": "asc"})
    # sort_config schema:
    # {
    #   "field": "priority" | "deadline" | "created_at" | "scheduled_at" | "title",
    #   "direction": "asc" | "desc"
    # }

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

### Default Views (seeded on user creation)

| Name           | filter_config                                                  |
|----------------|----------------------------------------------------------------|
| Today          | `{"due_within_days": 0, "status": ["pending", "scheduled"]}`  |
| This Week      | `{"due_within_days": 7, "status": ["pending", "scheduled"]}`  |
| Unscheduled    | `{"is_scheduled": false, "status": ["pending"]}`              |
| High Priority  | `{"priority": [1, 2], "status": ["pending", "scheduled"]}`    |

---

## BlackoutDay

Days where nothing should be scheduled. Break days.

```python
class BlackoutDay(Base):
    __tablename__ = "blackout_days"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "date"),)
```

---

## ScheduleLog

Audit trail for scheduling decisions. Essential for debugging and improving the engine.

```python
class ScheduleLog(Base):
    __tablename__ = "schedule_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    # Actions: "scheduled", "rescheduled", "unscheduled", "split", "failed", "skipped"
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    # details: {"reason": "...", "old_slot": "...", "new_slot": "...", "gcal_event_id": "..."}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

---

## Relationships

```
User 1──* Task
User 1──* Project
User 1──* Tag
User 1──* View
User 1──* BlackoutDay

Project 1──* Task

Task *──* Tag    (via task_tags)
Project *──* Tag (via project_tags)

Task.depends_on → [Task.id, ...]  (stored as array, not FK)
```