from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class SqlUserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        return await self.session.scalar(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )

    async def get_by_username(self, username: str) -> User | None:
        return await self.session.scalar(
            select(User).where(func.lower(User.username) == username.removeprefix("@").lower())
        )

    async def clear_username_from_other_users(
        self, username: str, telegram_user_id: int
    ) -> None:
        await self.session.execute(
            update(User)
            .where(
                func.lower(User.username) == username.lower(),
                User.telegram_user_id != telegram_user_id,
            )
            .values(username=None)
        )

    async def save(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user
