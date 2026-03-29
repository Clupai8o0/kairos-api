import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from kairos.models.base import Base
from kairos.utils.cuid import cuid


class BlackoutDay(Base):
    __tablename__ = "blackout_days"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "date"),)
