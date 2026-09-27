from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class InternalAdmin(Base):
    __tablename__ = "internal_admins"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
