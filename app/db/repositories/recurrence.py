from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RecurrenceSeries, Task


class SqlRecurrenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, series_id: int, *, for_update: bool = False) -> RecurrenceSeries | None:
        statement = select(RecurrenceSeries).where(RecurrenceSeries.id == series_id)
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def save(self, series: RecurrenceSeries) -> RecurrenceSeries:
        self.session.add(series)
        await self.session.flush()
        return series

    async def due_series(self, now: datetime, limit: int = 100) -> list[RecurrenceSeries]:
        statement = (
            select(RecurrenceSeries)
            .where(
                RecurrenceSeries.is_active.is_(True),
                RecurrenceSeries.next_due_at.is_not(None),
                RecurrenceSeries.next_due_at <= now,
            )
            .order_by(RecurrenceSeries.next_due_at, RecurrenceSeries.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.scalars(statement)).all())

    async def find_instance(self, series_id: int, scheduled_due_at: datetime) -> Task | None:
        return await self.session.scalar(
            select(Task).where(
                Task.recurrence_series_id == series_id, Task.scheduled_due_at == scheduled_due_at
            )
        )
