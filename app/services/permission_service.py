from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import InternalAdmin, Task, User
from app.db.repositories.admin import SqlAdminRepository
from app.db.repositories.user import SqlUserRepository
from app.domain.enums import TaskStatus
from app.domain.exceptions import PermissionDenied, UserNotRegistered


class PermissionService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], owner_telegram_id: int):
        self.session_factory = session_factory
        self.owner_telegram_id = owner_telegram_id

    async def _user(self, session: AsyncSession, telegram_user_id: int) -> User:
        user = await SqlUserRepository(session).get_by_telegram_id(telegram_user_id)
        if user is None:
            raise UserNotRegistered(f"Telegram user {telegram_user_id} is not registered")
        return user

    async def is_admin(self, telegram_user_id: int, session: AsyncSession | None = None) -> bool:
        if telegram_user_id == self.owner_telegram_id:
            return True
        if session is None:
            async with self.session_factory() as new_session:
                return await self.is_admin(telegram_user_id, new_session)
        user = await SqlUserRepository(session).get_by_telegram_id(telegram_user_id)
        return bool(user and await SqlAdminRepository(session).get(user.id))

    async def can_start(
        self, task: Task, actor_telegram_id: int, session: AsyncSession | None = None
    ) -> bool:
        if task.status != TaskStatus.NEW:
            return False
        return any(item.user.telegram_user_id == actor_telegram_id for item in task.assignees)

    async def can_complete(
        self, task: Task, actor_telegram_id: int, session: AsyncSession | None = None
    ) -> bool:
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.WAITING_AUTHOR):
            return False
        return (
            task.creator.telegram_user_id == actor_telegram_id
            or any(item.user.telegram_user_id == actor_telegram_id for item in task.assignees)
            or await self.is_admin(actor_telegram_id, session)
        )

    async def can_edit(
        self, task: Task, actor_telegram_id: int, session: AsyncSession | None = None
    ) -> bool:
        return task.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED) and (
            task.creator.telegram_user_id == actor_telegram_id
            or await self.is_admin(actor_telegram_id, session)
        )

    async def can_reschedule(
        self, task: Task, actor_telegram_id: int, session: AsyncSession | None = None
    ) -> bool:
        return await self.can_edit(task, actor_telegram_id, session)

    async def can_change_assignees(
        self, task: Task, actor_telegram_id: int, session: AsyncSession | None = None
    ) -> bool:
        return await self.can_edit(task, actor_telegram_id, session)

    async def can_cancel(
        self, task: Task, actor_telegram_id: int, session: AsyncSession | None = None
    ) -> bool:
        return await self.can_edit(task, actor_telegram_id, session)

    async def can_manage_admins(self, actor_telegram_id: int) -> bool:
        return await self.is_admin(actor_telegram_id)

    async def list_admins(self, actor_telegram_id: int) -> list[User]:
        if not await self.can_manage_admins(actor_telegram_id):
            raise PermissionDenied("Only internal administrators can list administrators")
        async with self.session_factory() as session:
            rows = await SqlAdminRepository(session).list_all()
            users = [await SqlUserRepository(session).get_by_id(row.user_id) for row in rows]
            owner = await SqlUserRepository(session).get_by_telegram_id(self.owner_telegram_id)
            return ([owner] if owner else []) + [
                user for user in users if user and user.telegram_user_id != self.owner_telegram_id
            ]

    async def add_admin(self, actor_telegram_id: int, target_telegram_id: int) -> User:
        if not await self.can_manage_admins(actor_telegram_id):
            raise PermissionDenied("Only internal administrators can add administrators")
        async with self.session_factory() as session, session.begin():
            actor = await self._user(session, actor_telegram_id)
            target = await self._user(session, target_telegram_id)
            admins = SqlAdminRepository(session)
            if await admins.get(target.id) is None:
                await admins.add(InternalAdmin(user_id=target.id, added_by=actor.id))
            return target

    async def remove_admin(self, actor_telegram_id: int, target_telegram_id: int) -> None:
        if not await self.can_manage_admins(actor_telegram_id):
            raise PermissionDenied("Only internal administrators can remove administrators")
        if target_telegram_id == self.owner_telegram_id:
            raise PermissionDenied("The owner is the permanent last administrator")
        async with self.session_factory() as session, session.begin():
            target = await self._user(session, target_telegram_id)
            await SqlAdminRepository(session).remove(target.id)
