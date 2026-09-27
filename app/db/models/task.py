from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utc_now
from app.domain.enums import TaskEventType, TaskPriority, TaskStatus

if TYPE_CHECKING:
    from app.db.models.recurrence import RecurrenceSeries
    from app.db.models.user import User


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("recurrence_series_id", "scheduled_due_at", name="uq_task_series_due"),
        Index("ix_tasks_chat_status_due", "chat_id", "status", "due_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    creator_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[TaskPriority] = mapped_column(Enum(TaskPriority, native_enum=False))
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False), default=TaskStatus.NEW
    )
    previous_status: Mapped[TaskStatus | None] = mapped_column(Enum(TaskStatus, native_enum=False))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    scheduled_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    group_message_id: Mapped[int | None] = mapped_column(BigInteger)
    recurrence_series_id: Mapped[int | None] = mapped_column(ForeignKey("recurrence_series.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    unable_reason: Mapped[str | None] = mapped_column(Text)
    unable_actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(default=1)

    creator: Mapped["User"] = relationship(foreign_keys=[creator_user_id])
    assignees: Mapped[list["TaskAssignee"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    recurrence_series: Mapped["RecurrenceSeries | None"] = relationship(back_populates="tasks")


class TaskAssignee(Base):
    __tablename__ = "task_assignees"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    task: Mapped[Task] = relationship(back_populates="assignees")
    user: Mapped["User"] = relationship(back_populates="assigned_tasks")


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[TaskEventType] = mapped_column(Enum(TaskEventType, native_enum=False))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    task: Mapped[Task] = relationship(back_populates="events")
