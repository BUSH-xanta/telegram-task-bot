from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InternalAdmin


class SqlAdminRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int) -> InternalAdmin | None:
        return await self.session.get(InternalAdmin, user_id)

    async def list_all(self) -> list[InternalAdmin]:
        return list(
            (
                await self.session.scalars(select(InternalAdmin).order_by(InternalAdmin.created_at))
            ).all()
        )

    async def count(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(InternalAdmin)) or 0

    async def add(self, admin: InternalAdmin) -> InternalAdmin:
        self.session.add(admin)
        await self.session.flush()
        return admin

    async def remove(self, user_id: int) -> None:
        admin = await self.get(user_id)
        if admin:
            await self.session.delete(admin)
