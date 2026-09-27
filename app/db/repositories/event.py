from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TaskEvent


class SqlTaskEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, event: TaskEvent) -> TaskEvent:
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_for_task(self, task_id: int) -> list[TaskEvent]:
        statement = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.created_at, TaskEvent.id)
        )
        return list((await self.session.scalars(statement)).all())
