from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import TaskEvent, User
from app.db.repositories.event import SqlTaskEventRepository
from app.db.repositories.task import SqlTaskRepository
from app.db.repositories.user import SqlUserRepository
from app.domain.enums import TaskEventType
from app.domain.exceptions import InvalidAssignee, UserNotInChat, UserNotRegistered
from app.domain.ports import MembershipProvider
from app.domain.schemas import AssigneeData


class UserService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        membership_provider: MembershipProvider,
        allowed_chat_id: int,
    ):
        self.session_factory = session_factory
        self.membership_provider = membership_provider
        self.allowed_chat_id = allowed_chat_id

    async def _username_is_current(self, telegram_user_id: int, username: str) -> bool:
        """Reject a recycled/stale handle even if its former holder is still in chat."""
        lookup = getattr(self.membership_provider, "get_member_username", None)
        if lookup is None:
            return True  # Test providers may implement only the protocol's membership check.
        current = await lookup(self.allowed_chat_id, telegram_user_id)
        return current is not None and current.casefold() == username.casefold()

    async def upsert_from_telegram(
        self,
        telegram_user_id: int,
        username: str | None,
        first_name: str,
        last_name: str | None = None,
        *,
        is_chat_member: bool | None = None,
        private_chat_started: bool = False,
    ) -> User:
        async with self.session_factory() as session, session.begin():
            # Serialize first discovery and username transfers.  Otherwise two
            # updates may each see the previous holder before either commits.
            await session.execute(
                select(func.pg_advisory_xact_lock(func.hashtext(f"telegram-user:{telegram_user_id}")))
            )
            repo = SqlUserRepository(session)
            user = await repo.get_by_telegram_id(telegram_user_id)
            normalized_username = username.removeprefix("@") if username else None
            if normalized_username:
                await session.execute(
                    select(func.pg_advisory_xact_lock(func.hashtext(f"username:{normalized_username.lower()}")))
                )
                await repo.clear_username_from_other_users(normalized_username, telegram_user_id)
            if user is None:
                user = User(
                    telegram_user_id=telegram_user_id,
                    username=normalized_username,
                    first_name=first_name,
                    last_name=last_name,
                    is_chat_member=bool(is_chat_member),
                    private_chat_started=private_chat_started,
                )
            else:
                user.username = normalized_username
                user.first_name = first_name
                user.last_name = last_name
                if is_chat_member is not None:
                    user.is_chat_member = is_chat_member
                if private_chat_started:
                    user.private_chat_started = True
                    user.private_delivery_available = True
            return await repo.save(user)

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        async with self.session_factory() as session:
            return await SqlUserRepository(session).get_by_telegram_id(telegram_user_id)

    async def resolve_assignees(self, usernames: list[str]) -> list[AssigneeData]:
        if not usernames:
            raise InvalidAssignee("At least one assignee is required")
        names = [name.removeprefix("@").strip() for name in usernames]
        if any(not name for name in names) or len({name.lower() for name in names}) != len(names):
            raise InvalidAssignee("Assignee usernames must be nonempty and unique")
        result: list[AssigneeData] = []
        async with self.session_factory() as session, session.begin():
            repo = SqlUserRepository(session)
            for name in names:
                user = await repo.get_by_username(name)
                if user is None:
                    raise UserNotRegistered(f"@{name} is not registered")
                member = await self.membership_provider.is_member(
                    self.allowed_chat_id, user.telegram_user_id
                )
                user.is_chat_member = member
                if not member:
                    raise UserNotInChat(f"@{name} is not a member of the working chat")
                if not await self._username_is_current(user.telegram_user_id, name):
                    raise UserNotRegistered(f"@{name} is no longer registered with that username")
                result.append(
                    AssigneeData(
                        user_id=user.id,
                        telegram_user_id=user.telegram_user_id,
                        username=user.username or name,
                        private_chat_started=user.private_chat_started,
                    )
                )
        return result

    async def validate_assignee_ids(self, user_ids: list[int]) -> list[User]:
        if not user_ids or len(set(user_ids)) != len(user_ids):
            raise InvalidAssignee("At least one distinct assignee is required")
        users: list[User] = []
        async with self.session_factory() as session, session.begin():
            repo = SqlUserRepository(session)
            for user_id in user_ids:
                user = await repo.get_by_id(user_id)
                if not user or not user.username:
                    raise UserNotRegistered(f"User {user_id} has no registered username")
                member = await self.membership_provider.is_member(
                    self.allowed_chat_id, user.telegram_user_id
                )
                user.is_chat_member = member
                if not member:
                    raise UserNotInChat(f"@{user.username} is not in the working chat")
                if not await self._username_is_current(user.telegram_user_id, user.username):
                    raise UserNotRegistered(
                        f"@{user.username} is no longer registered with that username"
                    )
                users.append(user)
        return users

    async def handle_member_left(self, telegram_user_id: int) -> list:
        async with self.session_factory() as session, session.begin():
            user = await SqlUserRepository(session).get_by_telegram_id(telegram_user_id)
            if user is None:
                return []
            user.is_chat_member = False
            tasks = await SqlTaskRepository(session).active_for_assignee(user.id)
            events = SqlTaskEventRepository(session)
            for task in tasks:
                await events.add(
                    TaskEvent(
                        task_id=task.id,
                        actor_user_id=user.id,
                        event_type=TaskEventType.ASSIGNEE_LEFT_CHAT,
                        payload={"username": user.username, "telegram_user_id": telegram_user_id},
                    )
                )
            return tasks
