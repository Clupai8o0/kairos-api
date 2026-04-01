import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos.models.base import Base
from kairos.utils.cuid import cuid


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)

    # Core
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_mins: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Scheduling
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.PENDING)
    schedulable: Mapped[bool] = mapped_column(Boolean, default=True)

    # Google Calendar reference
    gcal_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Flexibility
    buffer_mins: Mapped[int] = mapped_column(Integer, default=15)
    min_chunk_mins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_splittable: Mapped[bool] = mapped_column(Boolean, default=False)

    # Dependencies
    depends_on: Mapped[list] = mapped_column(ARRAY(String), default=list)

    # Recurrence
    recurrence_rule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    parent_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    recurrence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Metadata
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # Timestamps
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="tasks")  # noqa: F821
    project: Mapped["Project"] = relationship(back_populates="tasks")  # noqa: F821
    tags: Mapped[list["Tag"]] = relationship(  # noqa: F821
        secondary="task_tags", back_populates="tasks"
    )
    # Self-referential: occurrence instances back to their template
    recurrence_instances: Mapped[list["Task"]] = relationship(
        "Task",
        foreign_keys="Task.parent_task_id",
        back_populates="parent_task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    parent_task: Mapped["Task | None"] = relationship(
        "Task",
        foreign_keys="Task.parent_task_id",
        back_populates="recurrence_instances",
        remote_side="Task.id",
    )
