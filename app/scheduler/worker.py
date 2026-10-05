"""Polling worker for recurrence, persistent reminders, retries and digest."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.common import BotTaskCardPublisher, TelegramMembershipProvider
from app.db.models import Task
from app.domain.enums import TaskStatus
from app.scheduler.delivery import NotificationDispatcher
from app.services.notification_service import NotificationService
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)


class SchedulerWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bot: Bot,
        allowed_chat_id: int,
        owner_telegram_id: int = 0,
    ) -> None:
        self.session_factory = session_factory
        self.bot = bot
        self.dispatcher = NotificationDispatcher(session_factory, bot, allowed_chat_id)
        self.allowed_chat_id = allowed_chat_id
        task_service = TaskService(
            session_factory,
            allowed_chat_id,
            owner_telegram_id,
            TelegramMembershipProvider(bot),
        )
        self.card_publisher = BotTaskCardPublisher(bot, task_service, allowed_chat_id)

    async def run_once(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        await self._create_recurrences(now)
        await self._refresh_schedules(now)
        await self.dispatcher.materialize_due(now)
        await self.dispatcher.deliver_due(now)
        await self._publish_missing_cards(now)

    async def _create_recurrences(self, now: datetime) -> None:
        from app.services.recurrence_service import RecurrenceService

        service = RecurrenceService(self.session_factory)
        await service.create_due_instances(now=now)

    async def _publish_missing_cards(self, now: datetime, limit: int = 20) -> None:
        """Retry cards after Telegram errors, using the UI's locked publisher."""
        last_id = 0
        for _ in range(limit):
            async with self.session_factory() as session:
                task_id = await session.scalar(
                    select(Task.id)
                    .where(
                        Task.id > last_id,
                        Task.chat_id == self.allowed_chat_id,
                        Task.group_message_id.is_(None),
                        Task.status.in_(
                            (TaskStatus.NEW, TaskStatus.IN_PROGRESS, TaskStatus.WAITING_AUTHOR)
                        ),
                        or_(
                            Task.recurrence_series_id.is_not(None),
                            Task.created_at <= now - timedelta(seconds=30),
                        ),
                    )
                    .order_by(Task.id)
                    .limit(1)
                )
            if task_id is None:
                return
            last_id = task_id
            try:
                await self.card_publisher.publish(task_id)
            except Exception:
                logger.exception("Could not publish task card for task %s", task_id)
                return

    async def _refresh_schedules(self, now: datetime) -> None:
        """Only shared digests at 09:00 and 20:00 are scheduled."""
        async with self.session_factory.begin() as session:
            await NotificationService(session).schedule_digest(now=now)

    async def run_forever(self, interval_seconds: int = 5) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler worker cycle failed")
            await asyncio.sleep(interval_seconds)
