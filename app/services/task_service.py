from collections.abc import Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RecurrenceSeries, Task, TaskAssignee, TaskEvent
from app.db.repositories.event import SqlTaskEventRepository
from app.db.repositories.recurrence import SqlRecurrenceRepository
from app.db.repositories.task import SqlTaskRepository
from app.db.repositories.user import SqlUserRepository
from app.domain.enums import TaskEventType, TaskStatus
from app.domain.exceptions import (
    InvalidDeadline,
    InvalidTaskState,
    PermissionDenied,
    TaskNotFound,
    UserNotRegistered,
)
from app.domain.ports import MembershipProvider
from app.domain.schemas import TaskCreateData, TaskUpdateData
from app.services.permission_service import PermissionService
from app.services.recurrence_service import RecurrenceService, next_occurrence
from app.services.user_service import UserService
from app.utils.datetime import MOSCOW, now_moscow


def _valid_due(due_at: datetime) -> datetime:
    if due_at.tzinfo is None:
        raise InvalidDeadline("Deadline must have a timezone")
    due = due_at.astimezone(MOSCOW)
    if (due.hour, due.minute, due.second, due.microsecond) != (23, 59, 59, 0):
        raise InvalidDeadline("Deadline must be 23:59:59 Europe/Moscow")
    if due.date() < now_moscow().date():
        raise InvalidDeadline("Deadline cannot be in the past")
    return due


class TaskService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        allowed_chat_id: int,
        owner_telegram_id: int,
        membership_provider: MembershipProvider,
        notification_service_factory: Callable | None = None,
    ):
        self.session_factory = session_factory
        self.allowed_chat_id = allowed_chat_id
        self.owner_telegram_id = owner_telegram_id
        self.membership_provider = membership_provider
        self.notification_service_factory = notification_service_factory
        self.permissions = PermissionService(session_factory, owner_telegram_id)
        self.users = UserService(session_factory, membership_provider, allowed_chat_id)

    def _notifications(self, session: AsyncSession):
        if self.notification_service_factory is None:
            from app.services.notification_service import NotificationService

            return NotificationService(session)
        return self.notification_service_factory(session)

    async def _actor(self, session: AsyncSession, telegram_id: int):
        actor = await SqlUserRepository(session).get_by_telegram_id(telegram_id)
        if actor is None:
            raise UserNotRegistered(f"Telegram user {telegram_id} is not registered")
        return actor

    async def _task(self, session: AsyncSession, task_id: int) -> Task:
        task = await SqlTaskRepository(session).get(task_id, for_update=True)
        if task is None or task.chat_id != self.allowed_chat_id:
            raise TaskNotFound(f"Task #{task_id} was not found")
        return task

    async def _event(
        self,
        session: AsyncSession,
        task_id: int,
        actor_id: int | None,
        kind: TaskEventType,
        payload: dict | None = None,
    ) -> None:
        await SqlTaskEventRepository(session).add(
            TaskEvent(
                task_id=task_id, actor_user_id=actor_id, event_type=kind, payload=payload or {}
            )
        )

    @staticmethod
    def _set_assignees(task: Task, user_ids: list[int]) -> None:
        """Reuse overlapping rows to avoid insert-before-delete primary key collisions."""
        existing = {item.user_id: item for item in task.assignees}
        task.assignees = [
            existing.get(user_id) or TaskAssignee(user_id=user_id) for user_id in user_ids
        ]

    async def create(self, data: TaskCreateData, actor_telegram_id: int) -> Task:
        if data.chat_id != self.allowed_chat_id:
            raise PermissionDenied("Tasks can only be created in the working chat")
        title = data.title.strip()
        if not title:
            raise ValueError("Title is required")
        due = _valid_due(data.due_at)
        await self.users.validate_assignee_ids(data.assignee_user_ids)
        if data.recurrence and data.recurrence.end_date < due.date():
            raise InvalidDeadline("Recurrence end date precedes the first deadline")
        async with self.session_factory() as session, session.begin():
            actor = await self._actor(session, actor_telegram_id)
            if actor.id != data.creator_user_id:
                raise PermissionDenied("Creator must be the acting Telegram user")
            if not await self.membership_provider.is_member(
                self.allowed_chat_id, actor_telegram_id
            ):
                raise PermissionDenied("Creator is not in the working chat")
            series = None
            if data.recurrence:
                series = RecurrenceSeries(
                    chat_id=data.chat_id,
                    creator_user_id=actor.id,
                    title=title,
                    description=data.description,
                    priority=data.priority,
                    assignee_user_ids=data.assignee_user_ids,
                    interval_value=data.recurrence.interval_value,
                    interval_unit=data.recurrence.interval_unit,
                    base_due_at=due,
                    next_due_at=None,
                    end_date=data.recurrence.end_date,
                    is_active=True,
                )
                series.next_due_at = next_occurrence(series, due)
                series.is_active = series.next_due_at is not None
                session.add(series)
                await session.flush()
            task = Task(
                chat_id=data.chat_id,
                creator_user_id=actor.id,
                title=title,
                description=data.description,
                priority=data.priority,
                status=TaskStatus.NEW,
                due_at=due,
                recurrence_series_id=series.id if series else None,
                scheduled_due_at=due if series else None,
            )
            task.assignees = [TaskAssignee(user_id=user_id) for user_id in data.assignee_user_ids]
            session.add(task)
            await session.flush()
            await self._event(
                session,
                task.id,
                actor.id,
                TaskEventType.TASK_CREATED,
                {"due_at": due.isoformat(), "assignee_user_ids": data.assignee_user_ids},
            )
            await self._notifications(session).schedule_task(task.id)
            task_id = task.id
        return await self.get(task_id)

    async def get(self, task_id: int) -> Task:
        async with self.session_factory() as session:
            task = await SqlTaskRepository(session).get(task_id)
            if task is None or task.chat_id != self.allowed_chat_id:
                raise TaskNotFound(f"Task #{task_id} was not found")
            return task

    async def list_tasks(
        self,
        *,
        filter: str = "active",
        actor_telegram_id: int | None = None,
        sort: str = "due",
        page: int = 1,
    ) -> tuple[list[Task], int]:
        if actor_telegram_id is not None:
            admin = await self.permissions.is_admin(actor_telegram_id)
            member = admin or await self.membership_provider.is_member(
                self.allowed_chat_id, actor_telegram_id
            )
            if not member:
                raise PermissionDenied(
                    "Task lists are available only to members or internal admins"
                )
        async with self.session_factory() as session:
            actor_user_id = None
            if filter in {"mine", "created"}:
                if actor_telegram_id is None:
                    raise PermissionDenied("User identity is required")
                actor_user_id = (await self._actor(session, actor_telegram_id)).id
            return await SqlTaskRepository(session).list_page(
                self.allowed_chat_id,
                category=filter,
                actor_user_id=actor_user_id,
                sort=sort,
                page=page,
            )

    async def history(self, task_id: int) -> list[TaskEvent]:
        async with self.session_factory() as session:
            task = await SqlTaskRepository(session).get(task_id)
            if task is None or task.chat_id != self.allowed_chat_id:
                raise TaskNotFound(f"Task #{task_id} was not found")
            return await SqlTaskEventRepository(session).list_for_task(task_id)

    async def set_group_message_id(self, task_id: int, message_id: int) -> None:
        async with self.session_factory() as session, session.begin():
            task = await self._task(session, task_id)
            task.group_message_id = message_id

    async def start(self, task_id: int, actor_telegram_id: int) -> Task:
        async with self.session_factory() as session, session.begin():
            task = await self._task(session, task_id)
            if task.status == TaskStatus.IN_PROGRESS:
                if not any(
                    item.user.telegram_user_id == actor_telegram_id for item in task.assignees
                ):
                    raise PermissionDenied("Only an assigned executor can start a task")
                return task
            if not await self.permissions.can_start(task, actor_telegram_id, session):
                raise PermissionDenied("Only an assigned executor can start a new task")
            actor = await self._actor(session, actor_telegram_id)
            task.status = TaskStatus.IN_PROGRESS
            task.started_at = now_moscow()
            await self._event(session, task.id, actor.id, TaskEventType.TASK_STARTED)
        return await self.get(task_id)

    async def complete(self, task_id: int, actor_telegram_id: int) -> Task:
        async with self.session_factory() as session, session.begin():
            task = await self._task(session, task_id)
            if task.status == TaskStatus.COMPLETED:
                if not (
                    task.creator.telegram_user_id == actor_telegram_id
                    or any(
                        item.user.telegram_user_id == actor_telegram_id for item in task.assignees
                    )
                    or await self.permissions.is_admin(actor_telegram_id, session)
                ):
                    raise PermissionDenied("User cannot complete this task")
                return task
            if not await self.permissions.can_complete(task, actor_telegram_id, session):
                raise PermissionDenied("User cannot complete this task")
            actor = await self._actor(session, actor_telegram_id)
            task.status = TaskStatus.COMPLETED
            task.completed_at = now_moscow()
            await self._event(session, task.id, actor.id, TaskEventType.TASK_COMPLETED)
            await self._notifications(session).cancel_task(task.id)
            if task.recurrence_series_id:
                series = await SqlRecurrenceRepository(session).get(
                    task.recurrence_series_id, for_update=True
                )
                if series and series.is_active:
                    from sqlalchemy import select

                    latest_id = await session.scalar(
                        select(Task.id)
                        .where(Task.recurrence_series_id == series.id)
                        .order_by(Task.scheduled_due_at.desc())
                        .limit(1)
                    )
                    if latest_id == task.id:
                        recurrence = RecurrenceService(
                            self.session_factory, self.notification_service_factory
                        )
                        await recurrence._create_one(session, series)
        return await self.get(task_id)

    async def unable(self, task_id: int, actor_telegram_id: int, reason: str) -> Task:
        reason = reason.strip()
        if not reason:
            raise ValueError("A reason is required")
        async with self.session_factory() as session, session.begin():
            task = await self._task(session, task_id)
            if task.status not in (TaskStatus.NEW, TaskStatus.IN_PROGRESS):
                raise InvalidTaskState("Only active tasks can be blocked")
            if not any(item.user.telegram_user_id == actor_telegram_id for item in task.assignees):
                raise PermissionDenied("Only an assignee can report inability")
            actor = await self._actor(session, actor_telegram_id)
            task.previous_status = task.status
            task.status = TaskStatus.WAITING_AUTHOR
            task.unable_reason = reason
            task.unable_actor_user_id = actor.id
            await self._event(
                session, task.id, actor.id, TaskEventType.TASK_UNABLE, {"reason": reason}
            )
            await self._notifications(session).cancel_task(task.id)
        return await self.get(task_id)

    async def resolve_deadline(
        self, task_id: int, actor_telegram_id: int, due_at: datetime
    ) -> Task:
        due = _valid_due(due_at)
        async with self.session_factory() as session, session.begin():
            task = await self._task(session, task_id)
            if not await self.permissions.can_reschedule(task, actor_telegram_id, session):
                raise PermissionDenied("Only the author or admin can change the deadline")
            actor = await self._actor(session, actor_telegram_id)
            old = task.due_at
            task.due_at = due
            await self._event(
                session,
                task.id,
                actor.id,
                TaskEventType.DEADLINE_CHANGED,
                {"old": old.isoformat(), "new": due.isoformat()},
            )
            if task.status == TaskStatus.WAITING_AUTHOR:
                task.status = task.previous_status or TaskStatus.NEW
                task.previous_status = None
                task.unable_reason = None
                task.unable_actor_user_id = None
                await self._event(
                    session,
                    task.id,
                    actor.id,
                    TaskEventType.TASK_RESOLVED,
                    {"decision": "new_deadline"},
                )
            await self._sync_series(session, task)
            await self._notifications(session).reschedule_task(task.id)
        return await self.get(task_id)

    async def replace_assignees(
        self, task_id: int, actor_telegram_id: int, assignee_user_ids: list[int]
    ) -> Task:
        await self.users.validate_assignee_ids(assignee_user_ids)
        async with self.session_factory() as session, session.begin():
            task = await self._task(session, task_id)
            if not await self.permissions.can_change_assignees(task, actor_telegram_id, session):
                raise PermissionDenied("Only the author or admin can change assignees")
            actor = await self._actor(session, actor_telegram_id)
            old = [item.user_id for item in task.assignees]
            if set(old) == set(assignee_user_ids):
                return task
            was_waiting = task.status == TaskStatus.WAITING_AUTHOR
            self._set_assignees(task, assignee_user_ids)
            task.status = TaskStatus.NEW
            task.previous_status = None
            task.started_at = None
            task.unable_reason = None
            task.unable_actor_user_id = None
            await self._event(
                session,
                task.id,
                actor.id,
                TaskEventType.ASSIGNEES_CHANGED,
                {"old": old, "new": assignee_user_ids},
            )
            if was_waiting:
                await self._event(
                    session,
                    task.id,
                    actor.id,
                    TaskEventType.TASK_RESOLVED,
                    {"decision": "replace_assignees"},
                )
            await self._sync_series(session, task)
            await self._notifications(session).reschedule_task(task.id)
        return await self.get(task_id)

    async def cancel(self, task_id: int, actor_telegram_id: int, reason: str) -> Task:
        reason = reason.strip()
        if not reason:
            raise ValueError("A cancellation reason is required")
        async with self.session_factory() as session, session.begin():
            task = await self._task(session, task_id)
            if task.status == TaskStatus.CANCELLED:
                if not (
                    task.creator.telegram_user_id == actor_telegram_id
                    or await self.permissions.is_admin(actor_telegram_id, session)
                ):
                    raise PermissionDenied("Only the author or admin can cancel the task")
                return task
            if not await self.permissions.can_cancel(task, actor_telegram_id, session):
                raise PermissionDenied("Only the author or admin can cancel the task")
            actor = await self._actor(session, actor_telegram_id)
            task.status = TaskStatus.CANCELLED
            task.cancelled_at = now_moscow()
            task.cancellation_reason = reason
            await self._event(
                session, task.id, actor.id, TaskEventType.TASK_CANCELLED, {"reason": reason}
            )
            await self._notifications(session).cancel_task(task.id)
        return await self.get(task_id)

    async def _sync_series(self, session: AsyncSession, task: Task) -> None:
        if not task.recurrence_series_id:
            return
        series = await SqlRecurrenceRepository(session).get(
            task.recurrence_series_id, for_update=True
        )
        if series is None:
            return
        series.title = task.title
        series.description = task.description
        series.priority = task.priority
        series.assignee_user_ids = [item.user_id for item in task.assignees]
        if task.due_at != task.scheduled_due_at:
            series.base_due_at = task.due_at
            series.next_due_at = next_occurrence(series, task.due_at)
            series.is_active = series.next_due_at is not None

    async def update_task(self, task_id: int, actor_telegram_id: int, data: TaskUpdateData) -> Task:
        changes = data.model_fields_set
        new_assignees = data.assignee_user_ids if "assignee_user_ids" in changes else None
        if new_assignees is not None:
            await self.users.validate_assignee_ids(new_assignees)
        due = _valid_due(data.due_at) if "due_at" in changes and data.due_at else None
        async with self.session_factory() as session, session.begin():
            task = await self._task(session, task_id)
            if not await self.permissions.can_edit(task, actor_telegram_id, session):
                raise PermissionDenied("Only the author or admin can edit this task")
            actor = await self._actor(session, actor_telegram_id)
            for field, kind in (
                ("title", TaskEventType.TITLE_CHANGED),
                ("description", TaskEventType.DESCRIPTION_CHANGED),
                ("priority", TaskEventType.PRIORITY_CHANGED),
            ):
                if field not in changes:
                    continue
                value = getattr(data, field)
                if field == "title":
                    value = value.strip() if value else ""
                    if not value:
                        raise ValueError("Title is required")
                old = getattr(task, field)
                if old != value:
                    setattr(task, field, value)
                    await self._event(
                        session,
                        task.id,
                        actor.id,
                        kind,
                        {
                            "old": str(old) if old is not None else None,
                            "new": str(value) if value is not None else None,
                        },
                    )
            if new_assignees is not None:
                old_ids = [item.user_id for item in task.assignees]
                if set(old_ids) != set(new_assignees):
                    was_waiting = task.status == TaskStatus.WAITING_AUTHOR
                    self._set_assignees(task, new_assignees)
                    task.status = TaskStatus.NEW
                    task.previous_status = None
                    task.started_at = None
                    task.unable_reason = None
                    task.unable_actor_user_id = None
                    await self._event(
                        session,
                        task.id,
                        actor.id,
                        TaskEventType.ASSIGNEES_CHANGED,
                        {"old": old_ids, "new": new_assignees},
                    )
                    if was_waiting:
                        await self._event(
                            session,
                            task.id,
                            actor.id,
                            TaskEventType.TASK_RESOLVED,
                            {"decision": "replace_assignees"},
                        )
            if due and task.due_at != due:
                old_due = task.due_at
                task.due_at = due
                await self._event(
                    session,
                    task.id,
                    actor.id,
                    TaskEventType.DEADLINE_CHANGED,
                    {"old": old_due.isoformat(), "new": due.isoformat()},
                )
            if "recurrence" in changes:
                config = data.recurrence
                if config is None:
                    if task.recurrence_series_id:
                        series = await SqlRecurrenceRepository(session).get(
                            task.recurrence_series_id, for_update=True
                        )
                        if series:
                            series.is_active = False
                            series.next_due_at = None
                    await self._event(
                        session,
                        task.id,
                        actor.id,
                        TaskEventType.RECURRENCE_CHANGED,
                        {"active": False},
                    )
                else:
                    if config.end_date < task.due_at.date():
                        raise InvalidDeadline("Recurrence end date precedes deadline")
                    if task.recurrence_series_id:
                        series = await SqlRecurrenceRepository(session).get(
                            task.recurrence_series_id, for_update=True
                        )
                    else:
                        series = RecurrenceSeries(
                            chat_id=task.chat_id,
                            creator_user_id=task.creator_user_id,
                            title=task.title,
                            description=task.description,
                            priority=task.priority,
                            assignee_user_ids=[a.user_id for a in task.assignees],
                            interval_value=config.interval_value,
                            interval_unit=config.interval_unit,
                            base_due_at=task.due_at,
                            next_due_at=None,
                            end_date=config.end_date,
                            is_active=True,
                        )
                        session.add(series)
                        await session.flush()
                        task.recurrence_series_id = series.id
                        task.scheduled_due_at = task.due_at
                    series.interval_value = config.interval_value
                    series.interval_unit = config.interval_unit
                    series.end_date = config.end_date
                    series.base_due_at = task.due_at
                    series.next_due_at = next_occurrence(series, task.due_at)
                    series.is_active = series.next_due_at is not None
                    await self._event(
                        session,
                        task.id,
                        actor.id,
                        TaskEventType.RECURRENCE_CHANGED,
                        {
                            "interval_value": config.interval_value,
                            "interval_unit": config.interval_unit.value,
                            "end_date": config.end_date.isoformat(),
                        },
                    )
            await self._sync_series(session, task)
            if changes:
                await self._notifications(session).reschedule_task(task.id)
        return await self.get(task_id)
