"""Transactional scheduling API used by task and recurrence services."""

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationDelivery, ScheduledNotification, Task
from app.domain.enums import DeliveryStatus, NotificationStatus, NotificationType, TaskStatus
from app.scheduler.jobs import (
    Reminder,
    future_reminders,
    next_digest_time,
    notification_key,
    overdue_reminders,
)


class NotificationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def schedule_task(self, task_id: int, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        task = await self.session.get(Task, task_id)
        if task is None or task.status in (
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
            TaskStatus.WAITING_AUTHOR,
        ):
            return
        if task.due_at > now:
            reminders = future_reminders(
                task.due_at, task.priority, now, created_at=task.created_at
            )
        else:
            reminders = overdue_reminders(task.due_at, now)
        for reminder in reminders:
            await self._add(task_id, task.due_at, reminder)

    async def cancel_task(self, task_id: int) -> None:
        """Cancel unsent events; each delivery also checks task state before sending."""
        ids = select(ScheduledNotification.id).where(
            ScheduledNotification.task_id == task_id,
            ScheduledNotification.status.in_(
                (NotificationStatus.PENDING, NotificationStatus.PROCESSING)
            ),
        )
        await self.session.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.notification_id.in_(ids),
                NotificationDelivery.status.in_(
                    (DeliveryStatus.PENDING, DeliveryStatus.RETRY, DeliveryStatus.PROCESSING)
                ),
            )
            .values(status=DeliveryStatus.UNAVAILABLE, claimed_until=None)
        )
        await self.session.execute(
            update(ScheduledNotification)
            .where(ScheduledNotification.id.in_(ids))
            .values(status=NotificationStatus.CANCELLED, claimed_until=None)
        )

    async def reschedule_task(self, task_id: int, *, now: datetime | None = None) -> None:
        await self.cancel_task(task_id)
        # Cancelled rows have never been delivered. Remove them so resolving a
        # WAITING_AUTHOR task can recreate the same future slots and recipients.
        await self.session.execute(
            delete(ScheduledNotification).where(
                ScheduledNotification.task_id == task_id,
                ScheduledNotification.status == NotificationStatus.CANCELLED,
            )
        )
        await self.schedule_task(task_id, now=now)

    async def schedule_digest(self, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        when = next_digest_time(now)
        statement = insert(ScheduledNotification).values(
            task_id=None,
            notification_type=NotificationType.DAILY_SUMMARY,
            scheduled_at=when,
            status=NotificationStatus.PENDING,
            deduplication_key=f"digest:{when.date().isoformat()}",
        )
        await self.session.execute(
            statement.on_conflict_do_nothing(index_elements=["deduplication_key"])
        )

    async def _add(self, task_id: int, due_at: datetime, reminder: Reminder) -> None:
        statement = insert(ScheduledNotification).values(
            task_id=task_id,
            notification_type=reminder.kind,
            scheduled_at=reminder.scheduled_at,
            status=NotificationStatus.PENDING,
            deduplication_key=notification_key(task_id, reminder, due_at),
        )
        await self.session.execute(
            statement.on_conflict_do_nothing(index_elements=["deduplication_key"])
        )
