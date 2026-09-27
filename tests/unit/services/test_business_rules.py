from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.db.models import RecurrenceSeries, Task, TaskAssignee, User
from app.domain.enums import RecurrenceUnit, TaskPriority, TaskStatus
from app.domain.exceptions import InvalidDeadline, PermissionDenied
from app.services import task_service as task_module
from app.services.permission_service import PermissionService
from app.services.recurrence_service import next_occurrence, scheduled_occurrence
from app.services.task_service import TaskService, _valid_due
from app.utils.datetime import MOSCOW, due_at_moscow, now_moscow


@pytest.mark.parametrize(
    ("unit", "value", "expected"),
    [
        (RecurrenceUnit.DAYS, 2, date(2026, 2, 2)),
        (RecurrenceUnit.WEEKS, 2, date(2026, 2, 14)),
        (RecurrenceUnit.MONTHS, 1, date(2026, 2, 28)),
        (RecurrenceUnit.YEARS, 1, date(2027, 1, 31)),
    ],
)
def test_recurrence_units(unit, value, expected):
    result = scheduled_occurrence(due_at_moscow(date(2026, 1, 31)), value, unit, 1)
    assert result.date() == expected
    assert result.hour == 23 and result.minute == 59 and result.second == 59


def test_monthly_recurrence_uses_base_schedule():
    base = due_at_moscow(date(2026, 1, 31))
    assert scheduled_occurrence(base, 1, RecurrenceUnit.MONTHS, 2).date() == date(2026, 3, 31)


def test_recurrence_stops_at_end_date():
    base = due_at_moscow(date(2026, 1, 31))
    series = RecurrenceSeries(
        chat_id=-1,
        creator_user_id=1,
        title="test",
        priority=TaskPriority.NORMAL,
        assignee_user_ids=[2],
        interval_value=1,
        interval_unit=RecurrenceUnit.MONTHS,
        base_due_at=base,
        end_date=date(2026, 2, 27),
        is_active=True,
    )
    assert next_occurrence(series, base) is None
    series.end_date = date(2026, 2, 28)
    assert next_occurrence(series, base).date() == date(2026, 2, 28)


def test_deadline_rejects_past_and_wrong_time():
    today = now_moscow().date()
    assert _valid_due(due_at_moscow(today)).date() == today
    with pytest.raises(InvalidDeadline):
        _valid_due(due_at_moscow(today - timedelta(days=1)))
    with pytest.raises(InvalidDeadline):
        _valid_due(datetime.combine(today, datetime.min.time(), tzinfo=MOSCOW))


def test_replacing_assignees_reuses_existing_rows():
    retained = TaskAssignee(user_id=2)
    task = Task(assignees=[TaskAssignee(user_id=1), retained])
    TaskService._set_assignees(task, [2, 3])
    assert [item.user_id for item in task.assignees] == [2, 3]
    assert task.assignees[0] is retained


@pytest.mark.asyncio
async def test_permissions_use_telegram_ids_and_assignees():
    creator = User(id=1, telegram_user_id=101, username="author", first_name="A")
    executor = User(id=2, telegram_user_id=202, username="worker", first_name="B")
    task = Task(
        id=3,
        chat_id=-1,
        creator_user_id=1,
        creator=creator,
        title="test",
        priority=TaskPriority.NORMAL,
        status=TaskStatus.NEW,
        due_at=due_at_moscow(now_moscow().date()),
        assignees=[TaskAssignee(user_id=2, user=executor)],
    )
    permissions = PermissionService(None, owner_telegram_id=999)

    async def is_admin(telegram_user_id, session=None):
        return telegram_user_id == 999

    permissions.is_admin = is_admin
    assert await permissions.can_start(task, 202)
    assert not await permissions.can_start(task, 101)
    assert not await permissions.can_start(task, 303)
    assert await permissions.can_complete(task, 202)
    assert await permissions.can_complete(task, 101)
    assert await permissions.can_complete(task, 999)
    assert not await permissions.can_edit(task, 202)
    assert await permissions.can_edit(task, 101)
    assert await permissions.can_edit(task, 999)
    task.status = TaskStatus.WAITING_AUTHOR
    assert not await permissions.can_complete(task, 202)


@pytest.mark.asyncio
async def test_task_list_rejects_nonmember_even_for_archive():
    class Membership:
        async def is_member(self, _chat_id, _telegram_id):
            return False

    service = TaskService(None, -1001, 999, Membership())
    service.permissions.is_admin = AsyncMock(return_value=False)
    with pytest.raises(PermissionDenied):
        await service.list_tasks(filter="archive", actor_telegram_id=202)


@pytest.mark.asyncio
async def test_internal_owner_can_list_tasks_without_group_membership(monkeypatch):
    class Membership:
        async def is_member(self, _chat_id, _telegram_id):
            raise AssertionError("Owner does not require a group membership lookup")

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Tasks:
        def __init__(self, _session):
            pass

        async def list_page(self, *_args, **_kwargs):
            return [], 0

    monkeypatch.setattr(task_module, "SqlTaskRepository", Tasks)
    service = TaskService(lambda: Session(), -1001, 999, Membership())
    assert await service.list_tasks(filter="archive", actor_telegram_id=999) == ([], 0)
