from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.enums import DeliveryStatus, NotificationStatus, NotificationType, TaskStatus
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
@pytest.mark.parametrize(
    "kind", [kind for kind in NotificationType if kind != NotificationType.DAILY_SUMMARY]
)
async def test_task_reminders_only_target_available_private_recipients(kind) -> None:
    now = datetime(2026, 9, 30, 7, tzinfo=MOSCOW)
    notification = SimpleNamespace(
        id=5,
        task_id=42,
        scheduled_at=now,
        notification_type=kind,
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
    assert session.execute.await_count == 1
    params = [
        call.args[0].compile(dialect=postgresql.dialect()).params
        for call in session.execute.await_args_list
    ]
    assert {item["recipient_chat_id"] for item in params} == {101}
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
async def test_no_private_recipients_does_not_fall_back_to_group_or_retry_forever():
    now = datetime(2026, 9, 30, 7, tzinfo=MOSCOW)
    notification = SimpleNamespace(
        id=5,
        task_id=42,
        notification_type=NotificationType.DUE_DAY,
        status=NotificationStatus.PENDING,
    )
    session = AsyncMock()
    session.scalars.side_effect = [MagicMock(all=lambda: [notification]), []]
    session.get.return_value = SimpleNamespace(
        id=42, status=TaskStatus.NEW, due_at=due_at_moscow(date(2026, 9, 30))
    )
    dispatcher = NotificationDispatcher(SessionFactoryStub(session), AsyncMock(), -1000)
    await dispatcher.materialize_due(now)
    session.execute.assert_not_awaited()
    assert notification.status == NotificationStatus.CANCELLED
    assert notification.claimed_until is None
    assert notification.processed_at == now


@pytest.mark.asyncio
async def test_previously_queued_group_reminder_is_not_sent():
    now = datetime(2026, 9, 30, 7, tzinfo=MOSCOW)
    session = AsyncMock()
    session.execute.return_value = MagicMock(first=lambda: SimpleNamespace(id=9, task_id=42))
    delivery = SimpleNamespace(
        notification_id=5, recipient_user_id=None, status=DeliveryStatus.PENDING
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
