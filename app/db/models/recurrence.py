from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.domain.enums import RecurrenceUnit, TaskPriority

if TYPE_CHECKING:
    from app.db.models.task import Task


class RecurrenceSeries(TimestampMixin, Base):
    __tablename__ = "recurrence_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    creator_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[TaskPriority] = mapped_column(Enum(TaskPriority, native_enum=False))
    assignee_user_ids: Mapped[list[int]] = mapped_column(JSONB)
    interval_value: Mapped[int] = mapped_column(Integer)
    interval_unit: Mapped[RecurrenceUnit] = mapped_column(Enum(RecurrenceUnit, native_enum=False))
    base_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tasks: Mapped[list["Task"]] = relationship(back_populates="recurrence_series")
