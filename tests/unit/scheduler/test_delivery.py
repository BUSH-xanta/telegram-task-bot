from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.enums import DeliveryStatus, NotificationStatus, NotificationType
from app.scheduler.delivery import NotificationDispatcher
from app.utils.datetime import MOSCOW


class SessionFactoryStub:
    def __init__(self, session):
        self.session = session

    def begin(self):
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=self.session)
        context.__aexit__ = AsyncMock(return_value=False)
        return context


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", [kind for kind in NotificationType if kind != NotificationType.DAILY_SUMMARY]
)
async def test_all_old_task_reminders_are_cancelled_without_recipients(kind):
    now = datetime(2026, 9, 30, 7, tzinfo=MOSCOW)
    notification = SimpleNamespace(
        id=5, task_id=42, notification_type=kind, status=NotificationStatus.PENDING
    )
    session = AsyncMock()
    session.scalars.return_value = MagicMock(all=lambda: [notification])
    dispatcher = NotificationDispatcher(SessionFactoryStub(session), AsyncMock(), -1000)
    assert await dispatcher.materialize_due(now) == 1
    session.execute.assert_not_awaited()
    assert notification.status == NotificationStatus.CANCELLED
    assert notification.claimed_until is None


@pytest.mark.asyncio
async def test_daily_summary_still_targets_the_group():
    now = datetime(2026, 9, 30, 20, tzinfo=MOSCOW)
    notification = SimpleNamespace(id=5, task_id=None, status=NotificationStatus.PENDING)
    session = AsyncMock()
    session.scalars.return_value = MagicMock(all=lambda: [notification])
    dispatcher = NotificationDispatcher(SessionFactoryStub(session), AsyncMock(), -1000)
    assert await dispatcher.materialize_due(now) == 1
    params = session.execute.await_args.args[0].compile(dialect=postgresql.dialect()).params
    assert params["recipient_chat_id"] == -1000
    assert params["recipient_user_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("recipient_user_id", [None, 7])
async def test_old_group_and_private_deliveries_are_not_sent(recipient_user_id):
    now = datetime(2026, 9, 30, 7, tzinfo=MOSCOW)
    session = AsyncMock()
    session.execute.return_value = MagicMock(first=lambda: SimpleNamespace(id=9, task_id=42))
    delivery = SimpleNamespace(
        notification_id=5, recipient_user_id=recipient_user_id, status=DeliveryStatus.PENDING
    )
    session.scalar.side_effect = [SimpleNamespace(id=42), delivery]
    session.get.return_value = SimpleNamespace(
        id=5, task_id=42, status=NotificationStatus.PROCESSING
    )
    bot = AsyncMock()
    dispatcher = NotificationDispatcher(SessionFactoryStub(session), bot, -1000)
    dispatcher._finish_if_done = AsyncMock()
    assert await dispatcher._deliver_one(now)
    bot.send_message.assert_not_awaited()
    assert delivery.status == DeliveryStatus.UNAVAILABLE
    dispatcher._finish_if_done.assert_awaited_once_with(session, 5)
