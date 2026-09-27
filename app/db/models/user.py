from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.task import TaskAssignee


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(32), index=True)
    first_name: Mapped[str] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    is_chat_member: Mapped[bool] = mapped_column(Boolean, default=False)
    private_chat_started: Mapped[bool] = mapped_column(Boolean, default=False)
    private_delivery_available: Mapped[bool] = mapped_column(Boolean, default=True)

    assigned_tasks: Mapped[list["TaskAssignee"]] = relationship(back_populates="user")


# A Telegram username can be held by only one known user at a time.  The
# case-insensitive index matches the lookup used when assigning executors.
Index("uq_users_username_ci", func.lower(User.username), unique=True)
