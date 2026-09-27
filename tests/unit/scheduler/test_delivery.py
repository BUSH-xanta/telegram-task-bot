from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.enums import NotificationStatus, NotificationType, TaskStatus
from app.scheduler.delivery import NotificationDispatcher
from app.utils.datetime import MOSCOW, due_at_moscow


class SessionFactoryStub:
    def __init__(self, session):
        self.session = session

    def begin(self):
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=self.session)
        context.__aexit__ = AsyncMock(return_value=False)
        return context


@pytest.mark.asyncio
async def test_group_delivery_survives_unavailable_private_recipient() -> None:
    now = datetime(2026, 9, 30, 7, tzinfo=MOSCOW)
    notification = SimpleNamespace(
        id=5,
        task_id=42,
        scheduled_at=now,
        notification_type=NotificationType.DUE_DAY,
        status=NotificationStatus.PENDING,
        claimed_until=None,
    )
    task = SimpleNamespace(id=42, status=TaskStatus.NEW, due_at=due_at_moscow(date(2026, 9, 30)))
    recipients = [
        SimpleNamespace(
            id=1,
            telegram_user_id=101,
            private_chat_started=True,
            private_delivery_available=True,
        ),
        SimpleNamespace(
            id=2,
            telegram_user_id=102,
            private_chat_started=True,
            private_delivery_available=False,
        ),
        SimpleNamespace(
            id=3,
            telegram_user_id=103,
            private_chat_started=False,
            private_delivery_available=True,
        ),
    ]
    session = AsyncMock()
    session.scalars.side_effect = [MagicMock(all=lambda: [notification]), recipients]
    session.get.return_value = task
    dispatcher = NotificationDispatcher(SessionFactoryStub(session), AsyncMock(), -1000)

    assert await dispatcher.materialize_due(now) == 1
    assert session.execute.await_count == 2
    params = [
        call.args[0].compile(dialect=postgresql.dialect()).params
        for call in session.execute.await_args_list
    ]
    assert {item["recipient_chat_id"] for item in params} == {-1000, 101}
    assert all("DO NOTHING" in str(call.args[0]) for call in session.execute.await_args_list)
    assert notification.status == NotificationStatus.PROCESSING


@pytest.mark.asyncio
async def test_completed_task_is_not_materialized() -> None:
    now = datetime(2026, 9, 30, 7, tzinfo=MOSCOW)
    notification = SimpleNamespace(
        id=5,
        task_id=42,
        scheduled_at=now,
        notification_type=NotificationType.DUE_DAY,
        status=NotificationStatus.PENDING,
        claimed_until=None,
    )
    session = AsyncMock()
    session.scalars.return_value = MagicMock(all=lambda: [notification])
    session.get.return_value = SimpleNamespace(status=TaskStatus.COMPLETED)
    dispatcher = NotificationDispatcher(SessionFactoryStub(session), AsyncMock(), -1000)

    assert await dispatcher.materialize_due(now) == 1
    assert notification.status == NotificationStatus.CANCELLED
    session.execute.assert_not_awaited()
