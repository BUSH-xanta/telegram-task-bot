from collections.abc import Callable
from datetime import datetime

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RecurrenceSeries, Task, TaskAssignee, TaskEvent
from app.db.repositories.event import SqlTaskEventRepository
from app.db.repositories.recurrence import SqlRecurrenceRepository
from app.domain.enums import RecurrenceUnit, TaskEventType, TaskStatus
from app.utils.datetime import now_moscow


def scheduled_occurrence(base: datetime, value: int, unit: RecurrenceUnit, index: int) -> datetime:
    """Calculate from the base, so January 31 recurs on March 31 after February 28."""
    amount = value * index
    if unit == RecurrenceUnit.DAYS:
        return base + relativedelta(days=amount)
    if unit == RecurrenceUnit.WEEKS:
        return base + relativedelta(weeks=amount)
    if unit == RecurrenceUnit.MONTHS:
        return base + relativedelta(months=amount)
    return base + relativedelta(years=amount)


def next_occurrence(series: RecurrenceSeries, after: datetime) -> datetime | None:
    index = 1
    while True:
        candidate = scheduled_occurrence(
            series.base_due_at, series.interval_value, series.interval_unit, index
        )
        if candidate > after:
            return candidate if candidate.date() <= series.end_date else None
        index += 1


class RecurrenceService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        notification_service_factory: Callable | None = None,
    ):
        self.session_factory = session_factory
        self.notification_service_factory = notification_service_factory

    def _notifications(self, session: AsyncSession):
        if self.notification_service_factory is None:
            from app.services.notification_service import NotificationService

            return NotificationService(session)
        return self.notification_service_factory(session)

    async def _create_one(self, session: AsyncSession, series: RecurrenceSeries) -> Task | None:
        due = series.next_due_at
        if not series.is_active or due is None:
            return None
        if due.date() > series.end_date:
            series.is_active = False
            series.next_due_at = None
            return None
        repo = SqlRecurrenceRepository(session)
        existing = await repo.find_instance(series.id, due)
        if existing is None:
            task = Task(
                chat_id=series.chat_id,
                creator_user_id=series.creator_user_id,
                title=series.title,
                description=series.description,
                priority=series.priority,
                status=TaskStatus.NEW,
                due_at=due,
                scheduled_due_at=due,
                recurrence_series_id=series.id,
            )
            task.assignees = [TaskAssignee(user_id=user_id) for user_id in series.assignee_user_ids]
            session.add(task)
            await session.flush()
            await SqlTaskEventRepository(session).add(
                TaskEvent(
                    task_id=task.id,
                    actor_user_id=None,
                    event_type=TaskEventType.RECURRENCE_INSTANCE_CREATED,
                    payload={"series_id": series.id, "scheduled_due_at": due.isoformat()},
                )
            )
            await self._notifications(session).schedule_task(task.id)
        else:
            task = existing
        series.next_due_at = next_occurrence(series, due)
        if series.next_due_at is None:
            series.is_active = False
        return task

    async def create_due_instances(
        self, now: datetime | None = None, limit: int = 100
    ) -> list[Task]:
        now = now or now_moscow()
        created: list[Task] = []
        async with self.session_factory() as session, session.begin():
            series_rows = await SqlRecurrenceRepository(session).due_series(now, limit)
            for series in series_rows:
                while series.next_due_at and series.next_due_at <= now:
                    task = await self._create_one(session, series)
                    if task:
                        created.append(task)
        return created

    async def create_next_after_completion(
        self, series_id: int, completed_task_id: int | None = None
    ) -> Task | None:
        async with self.session_factory() as session, session.begin():
            series = await SqlRecurrenceRepository(session).get(series_id, for_update=True)
            if not series or not series.is_active or not series.next_due_at:
                return None
            if completed_task_id is not None:
                latest_id = await session.scalar(
                    select(Task.id)
                    .where(Task.recurrence_series_id == series_id)
                    .order_by(Task.scheduled_due_at.desc())
                    .limit(1)
                )
                if latest_id != completed_task_id:
                    return None
            return await self._create_one(session, series)
