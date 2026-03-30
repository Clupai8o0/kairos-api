from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos.models.base import Base
from kairos.utils.cuid import cuid


class GoogleCalendar(Base):
    __tablename__ = "google_calendars"
    __table_args__ = (
        UniqueConstraint("account_id", "google_calendar_id", name="uq_google_calendar_account_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("google_accounts.id"), nullable=False, index=True
    )
    google_calendar_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    timezone: Mapped[str | None] = mapped_column(String, nullable=True)
    access_role: Mapped[str] = mapped_column(String, default="reader")
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    account: Mapped["GoogleAccount"] = relationship(back_populates="calendars")  # noqa: F821
