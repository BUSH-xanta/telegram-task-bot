from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.enums import TaskPriority, TaskStatus
from app.scheduler.delivery import NotificationDispatcher
from app.services.notification_service import NotificationService
from app.utils.datetime import MOSCOW, due_at_moscow


def _task(status: TaskStatus = TaskStatus.NEW, priority: TaskPriority = TaskPriority.NORMAL):
    return type(
        "TaskStub",
        (),
        {
            "status": status,
            "priority": priority,
            "due_at": due_at_moscow(date(2026, 9, 30)),
            "created_at": datetime(2026, 9, 20, tzinfo=MOSCOW),
        },
    )()


@pytest.mark.asyncio
@pytest.mark.parametrize("priority", list(TaskPriority))
async def test_tasks_do_not_schedule_individual_reminders(priority):
    session = AsyncMock()
    session.get.return_value = _task(priority=priority)
    await NotificationService(session).schedule_task(42, now=datetime(2026, 9, 20, tzinfo=MOSCOW))
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_digest_slots_have_distinct_persistent_keys():
    session = AsyncMock()
    await NotificationService(session).schedule_digest(now=datetime(2026, 9, 20, 8, tzinfo=MOSCOW))
    params = [
        call.args[0].compile(dialect=postgresql.dialect()).params
        for call in session.execute.await_args_list
    ]
    assert [row["scheduled_at"].hour for row in params] == [9, 20]
    assert len({row["deduplication_key"] for row in params}) == 2
    assert all(row["task_id"] is None for row in params)
    assert all("DO NOTHING" in str(call.args[0]) for call in session.execute.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.WAITING_AUTHOR]
)
async def test_inactive_tasks_have_no_future_notifications(status: TaskStatus) -> None:
    session = AsyncMock()
    session.get.return_value = _task(status)
    await NotificationService(session).schedule_task(42, now=datetime(2026, 9, 20, tzinfo=MOSCOW))
    session.execute.assert_not_awaited()


def test_retry_backoff_is_capped() -> None:
    row = type("DeliveryStub", (), {"attempt_count": 20})()
    now = datetime(2026, 9, 26, tzinfo=MOSCOW)
    NotificationDispatcher._set_retry(row, now, RuntimeError("temporary"))
    assert (row.next_attempt_at - now).total_seconds() == 3600
    assert row.last_error == "temporary"
