from datetime import UTC, date, datetime

import pytest

from app.domain.enums import NotificationType, TaskPriority
from app.scheduler.jobs import (
    future_reminders,
    next_digest_time,
    overdue_reminders,
    standard_reminders,
)
from app.utils.datetime import MOSCOW, due_at_moscow


def test_standard_schedule_has_all_six_slots() -> None:
    due = due_at_moscow(date(2026, 9, 30))
    reminders = standard_reminders(due, datetime(2026, 9, 20, tzinfo=MOSCOW))
    assert [(item.kind, item.scheduled_at.strftime("%d.%m %H:%M:%S")) for item in reminders] == [
        (NotificationType.BEFORE_7_DAYS, "23.09 07:00:00"),
        (NotificationType.BEFORE_3_DAYS, "27.09 07:00:00"),
        (NotificationType.BEFORE_1_DAY, "29.09 07:00:00"),
        (NotificationType.DUE_DAY, "30.09 07:00:00"),
        (NotificationType.BEFORE_3_HOURS, "30.09 20:59:59"),
        (NotificationType.AT_DEADLINE, "30.09 23:59:59"),
    ]


def test_past_slots_are_never_created() -> None:
    due = due_at_moscow(date(2026, 9, 30))
    now = datetime(2026, 9, 29, 8, tzinfo=MOSCOW)
    kinds = [r.kind for r in standard_reminders(due, now)]
    assert kinds == [
        NotificationType.DUE_DAY,
        NotificationType.BEFORE_3_HOURS,
        NotificationType.AT_DEADLINE,
    ]


def test_urgent_has_nine_and_twenty_one_and_merges_near_three_hour_slot() -> None:
    due = due_at_moscow(date(2026, 9, 30))
    reminders = future_reminders(due, TaskPriority.URGENT, datetime(2026, 9, 29, 22, tzinfo=MOSCOW))
    assert any(r.kind == NotificationType.URGENT and r.scheduled_at.hour == 9 for r in reminders)
    assert not any(
        r.kind == NotificationType.URGENT and r.scheduled_at.hour == 21 for r in reminders
    )
    assert len([r for r in reminders if r.scheduled_at.hour == 20]) == 1


def test_urgent_merging_still_works_when_rolling_window_moves() -> None:
    due = due_at_moscow(date(2026, 9, 30))
    now = datetime(2026, 9, 30, 20, 59, 59, 500000, tzinfo=MOSCOW)
    reminders = future_reminders(
        due, TaskPriority.URGENT, now, created_at=datetime(2026, 9, 20, tzinfo=MOSCOW)
    )
    assert not any(
        r.kind == NotificationType.URGENT and r.scheduled_at.hour == 21 for r in reminders
    )


def test_urgent_fires_when_created_after_nearby_standard_slot() -> None:
    due = due_at_moscow(date(2026, 9, 30))
    now = datetime(2026, 9, 30, 20, 59, 59, 500000, tzinfo=MOSCOW)
    reminders = future_reminders(due, TaskPriority.URGENT, now, created_at=now)
    assert any(r.kind == NotificationType.URGENT and r.scheduled_at.hour == 21 for r in reminders)


def test_overdue_slots_and_deadline_merge() -> None:
    due = due_at_moscow(date(2026, 9, 30))
    now = datetime(2026, 9, 30, 23, 59, 59, tzinfo=MOSCOW)
    reminders = overdue_reminders(due, now, horizon_days=1)
    assert [r.scheduled_at.hour for r in reminders] == [6, 12, 18]
    assert all(r.kind == NotificationType.OVERDUE for r in reminders)


def test_digest_runs_at_twenty_moscow() -> None:
    before = datetime(2026, 9, 26, 16, 59, tzinfo=UTC)
    after = datetime(2026, 9, 26, 17, 1, tzinfo=UTC)
    assert next_digest_time(before) == datetime(2026, 9, 26, 20, tzinfo=MOSCOW)
    assert next_digest_time(after) == datetime(2026, 9, 27, 20, tzinfo=MOSCOW)


def test_naive_times_rejected() -> None:
    with pytest.raises(ValueError):
        standard_reminders(due_at_moscow(date(2026, 9, 30)), datetime(2026, 9, 1))
