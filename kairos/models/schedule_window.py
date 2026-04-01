import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Time, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos.models.base import Base
from kairos.utils.cuid import cuid


class ScheduleWindow(Base):
    __tablename__ = "schedule_windows"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    days_of_week: Mapped[list] = mapped_column(ARRAY(String), nullable=False)
    start_time: Mapped[dt.time] = mapped_column(Time(), nullable=False)
    end_time: Mapped[dt.time] = mapped_column(Time(), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="schedule_windows")  # noqa: F821
