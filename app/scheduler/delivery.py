"""Claim and deliver notification outbox rows with PostgreSQL row locks."""

import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.models import NotificationDelivery, ScheduledNotification, Task, TaskAssignee, User
from app.domain.enums import DeliveryStatus, NotificationStatus, TaskStatus
from app.scheduler.render import digest_text

logger = logging.getLogger(__name__)
ACTIVE = (TaskStatus.NEW, TaskStatus.IN_PROGRESS)
TERMINAL_DELIVERY = (DeliveryStatus.SENT, DeliveryStatus.UNAVAILABLE)


class NotificationDispatcher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bot: Bot,
        allowed_chat_id: int,
    ) -> None:
        self.session_factory = session_factory
        self.bot = bot
        self.allowed_chat_id = allowed_chat_id

    async def materialize_due(self, now: datetime | None = None, limit: int = 100) -> int:
        now = now or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            statement = (
                select(ScheduledNotification)
                .where(
                    ScheduledNotification.scheduled_at <= now,
                    or_(
                        ScheduledNotification.status == NotificationStatus.PENDING,
                        and_(
                            ScheduledNotification.status == NotificationStatus.PROCESSING,
                            ScheduledNotification.claimed_until < now,
                        ),
                    ),
                )
                .order_by(ScheduledNotification.scheduled_at, ScheduledNotification.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            notifications = list((await session.scalars(statement)).all())
            for item in notifications:
                if item.task_id is None:
                    recipients: list[tuple[int, int | None]] = [(self.allowed_chat_id, None)]
                else:
                    item.status = NotificationStatus.CANCELLED
                    item.processed_at = now
                    item.claimed_until = None
                    continue
                for chat_id, user_id in recipients:
                    await session.execute(
                        insert(NotificationDelivery)
                        .values(
                            notification_id=item.id,
                            recipient_chat_id=chat_id,
                            recipient_user_id=user_id,
                            status=DeliveryStatus.PENDING,
                        )
                        .on_conflict_do_nothing(constraint="uq_notification_recipient")
                    )
                item.status = NotificationStatus.PROCESSING
                item.claimed_until = now + timedelta(minutes=2)
            return len(notifications)

    async def deliver_due(self, now: datetime | None = None, limit: int = 100) -> int:
        now = now or datetime.now(UTC)
        processed = 0
        for _ in range(limit):
            if not await self._deliver_one(now):
                break
            processed += 1
        return processed

    async def _deliver_one(self, now: datetime) -> bool:
        async with self.session_factory.begin() as session:
            due_filter = or_(
                NotificationDelivery.status == DeliveryStatus.PENDING,
                and_(
                    NotificationDelivery.status == DeliveryStatus.RETRY,
                    or_(
                        NotificationDelivery.next_attempt_at.is_(None),
                        NotificationDelivery.next_attempt_at <= now,
                    ),
                ),
                and_(
                    NotificationDelivery.status == DeliveryStatus.PROCESSING,
                    NotificationDelivery.claimed_until < now,
                ),
            )
            candidate = (
                await session.execute(
                    select(NotificationDelivery.id, ScheduledNotification.task_id)
                    .join(ScheduledNotification)
                    .where(due_filter)
                    .order_by(NotificationDelivery.id)
                    .limit(1)
                )
            ).first()
            if candidate is None:
                return False
            if candidate.task_id is not None:
                # Task services lock the task before cancelling its deliveries.
                # Follow the same order to avoid a completion/send deadlock.
                await session.scalar(
                    select(Task)
                    .options(selectinload(Task.assignees).selectinload(TaskAssignee.user))
                    .where(Task.id == candidate.task_id)
                    .with_for_update()
                )
            statement = (
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.id == candidate.id,
                    due_filter,
                )
                .with_for_update(skip_locked=True)
            )
            delivery = await session.scalar(statement)
            if delivery is None:
                return True
            notification = await session.get(ScheduledNotification, delivery.notification_id)
            if notification is None or notification.status == NotificationStatus.CANCELLED:
                delivery.status = DeliveryStatus.UNAVAILABLE
                return True
            if notification.task_id is not None:
                # Suppress all old per-task deliveries, including private retries.
                delivery.status = DeliveryStatus.UNAVAILABLE
                delivery.claimed_until = None
                await self._finish_if_done(session, notification.id)
                return True
            else:
                tasks = list(
                    (
                        await session.scalars(
                            select(Task)
                            .options(selectinload(Task.assignees).selectinload(TaskAssignee.user))
                            .where(Task.chat_id == self.allowed_chat_id, Task.status.in_(ACTIVE))
                        )
                    ).all()
                )
                message = digest_text(tasks, notification.scheduled_at)

            # Hold the task and delivery locks during the API call: a completion
            # cannot commit between the final status check and this send.
            delivery.status = DeliveryStatus.PROCESSING
            delivery.claimed_until = now + timedelta(minutes=2)
            delivery.attempt_count += 1
            try:
                sent = await self.bot.send_message(delivery.recipient_chat_id, message)
            except TelegramForbiddenError as exc:
                logger.warning(
                    "Telegram delivery forbidden for notification %s: %s", notification.id, exc
                )
                if delivery.recipient_user_id is not None:
                    await session.execute(
                        update(User)
                        .where(User.id == delivery.recipient_user_id)
                        .values(private_delivery_available=False)
                    )
                    delivery.status = DeliveryStatus.UNAVAILABLE
                else:
                    self._set_retry(delivery, now, exc)
            except TelegramRetryAfter as exc:
                logger.warning("Telegram rate limit for notification %s: %s", notification.id, exc)
                self._set_retry(delivery, now, exc, minimum_delay=exc.retry_after)
            except Exception as exc:
                logger.exception("Telegram delivery failed for notification %s", notification.id)
                self._set_retry(delivery, now, exc)
            else:
                delivery.status = DeliveryStatus.SENT
                delivery.sent_at = datetime.now(UTC)
                delivery.telegram_message_id = sent.message_id
                delivery.claimed_until = None
                delivery.next_attempt_at = None
                delivery.last_error = None
            await session.flush()
            await self._finish_if_done(session, notification.id)
            return True

    @staticmethod
    def _set_retry(
        delivery: NotificationDelivery,
        now: datetime,
        exc: Exception,
        minimum_delay: int | float = 0,
    ) -> None:
        delay = max(minimum_delay, min(3600, 2 ** min(delivery.attempt_count, 12)))
        delivery.status = DeliveryStatus.RETRY
        delivery.next_attempt_at = now + timedelta(seconds=delay)
        delivery.claimed_until = None
        delivery.last_error = str(exc)[:2000]

    @staticmethod
    async def _finish_if_done(session: AsyncSession, notification_id: int) -> None:
        unfinished = await session.scalar(
            select(NotificationDelivery.id)
            .where(
                NotificationDelivery.notification_id == notification_id,
                NotificationDelivery.status.not_in(TERMINAL_DELIVERY),
            )
            .limit(1)
        )
        if unfinished is None:
            await session.execute(
                update(ScheduledNotification)
                .where(
                    ScheduledNotification.id == notification_id,
                    ScheduledNotification.status != NotificationStatus.CANCELLED,
                )
                .values(
                    status=NotificationStatus.SENT,
                    processed_at=datetime.now(UTC),
                    claimed_until=None,
                )
            )
