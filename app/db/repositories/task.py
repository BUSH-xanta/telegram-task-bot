from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Task, TaskAssignee
from app.domain.enums import TaskPriority, TaskStatus
from app.utils.datetime import now_moscow

TASK_LOAD = (
    selectinload(Task.assignees).selectinload(TaskAssignee.user),
    selectinload(Task.creator),
    selectinload(Task.recurrence_series),
)
ACTIVE = (TaskStatus.NEW, TaskStatus.IN_PROGRESS, TaskStatus.WAITING_AUTHOR)


class SqlTaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, task_id: int, *, for_update: bool = False) -> Task | None:
        statement = select(Task).where(Task.id == task_id).options(*TASK_LOAD)
        if for_update:
            statement = statement.with_for_update(of=Task)
        return await self.session.scalar(statement)

    async def save(self, task: Task) -> Task:
        self.session.add(task)
        await self.session.flush()
        return task

    async def list_active(self, chat_id: int, *, offset: int = 0, limit: int = 10) -> list[Task]:
        statement = (
            select(Task)
            .where(Task.chat_id == chat_id, Task.status.in_(ACTIVE))
            .options(*TASK_LOAD)
            .order_by(Task.due_at, Task.id)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def list_page(
        self,
        chat_id: int,
        *,
        category: str = "active",
        actor_user_id: int | None = None,
        sort: str = "due",
        page: int = 1,
        limit: int = 10,
    ) -> tuple[list[Task], int]:
        statement = select(Task).where(Task.chat_id == chat_id)
        if category in {
            "active",
            "all",
            "mine",
            "created",
            "overdue",
            "new",
            "in_progress",
            "progress",
        }:
            statement = statement.where(Task.status.in_(ACTIVE))
        elif category == "archive":
            statement = statement.where(
                Task.status.in_((TaskStatus.COMPLETED, TaskStatus.CANCELLED))
            )
        elif category == "completed":
            statement = statement.where(Task.status == TaskStatus.COMPLETED)
        elif category == "cancelled":
            statement = statement.where(Task.status == TaskStatus.CANCELLED)
        else:
            raise ValueError("Unknown task category")
        if category == "mine":
            statement = statement.where(Task.assignees.any(TaskAssignee.user_id == actor_user_id))
        elif category == "created":
            statement = statement.where(Task.creator_user_id == actor_user_id)
        elif category == "overdue":
            statement = statement.where(
                Task.status != TaskStatus.WAITING_AUTHOR, Task.due_at < now_moscow()
            )
        elif category == "new":
            statement = statement.where(Task.status == TaskStatus.NEW)
        elif category in {"in_progress", "progress"}:
            statement = statement.where(Task.status == TaskStatus.IN_PROGRESS)
        total = (
            await self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        if sort == "priority":
            rank = case(
                (Task.priority == TaskPriority.URGENT, 0),
                (Task.priority == TaskPriority.HIGH, 1),
                (Task.priority == TaskPriority.NORMAL, 2),
                else_=3,
            )
            statement = statement.order_by(rank, Task.due_at, Task.id)
        elif sort == "created":
            statement = statement.order_by(Task.created_at.desc(), Task.id.desc())
        elif sort == "due":
            statement = statement.order_by(Task.due_at, Task.id)
        else:
            raise ValueError("Unknown sort order")
        statement = statement.options(*TASK_LOAD).offset((max(page, 1) - 1) * limit).limit(limit)
        return list((await self.session.scalars(statement)).all()), total

    async def active_for_assignee(self, user_id: int) -> list[Task]:
        statement = (
            select(Task)
            .where(Task.status.in_(ACTIVE), Task.assignees.any(TaskAssignee.user_id == user_id))
            .options(*TASK_LOAD)
            .order_by(Task.id)
        )
        return list((await self.session.scalars(statement)).all())
