"""Pure Moscow-time notification schedule calculations."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.domain.enums import NotificationType, TaskPriority
from app.utils.datetime import MOSCOW


@dataclass(frozen=True)
class Reminder:
    kind: NotificationType
    scheduled_at: datetime


def _morning(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=MOSCOW)


def standard_reminders(due_at: datetime, now: datetime) -> list[Reminder]:
    """Return future reminders, combining events within 15 minutes of one task."""
    if due_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("Notification datetimes must be timezone aware")
    local_due = due_at.astimezone(MOSCOW)
    day = local_due.date()
    candidates = [
        Reminder(NotificationType.BEFORE_7_DAYS, _morning(day - timedelta(days=7), 7)),
        Reminder(NotificationType.BEFORE_3_DAYS, _morning(day - timedelta(days=3), 7)),
        Reminder(NotificationType.BEFORE_1_DAY, _morning(day - timedelta(days=1), 7)),
        Reminder(NotificationType.DUE_DAY, _morning(day, 7)),
        Reminder(NotificationType.BEFORE_3_HOURS, local_due - timedelta(hours=3)),
        Reminder(NotificationType.AT_DEADLINE, local_due),
    ]
    return [r for r in candidates if r.scheduled_at > now and r.scheduled_at <= local_due]


def urgent_reminders(due_at: datetime, now: datetime, horizon_days: int = 7) -> list[Reminder]:
    if due_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("Notification datetimes must be timezone aware")
    local_now = now.astimezone(MOSCOW)
    local_due = due_at.astimezone(MOSCOW)
    result: list[Reminder] = []
    day = local_now.date()
    last_day = min(day + timedelta(days=horizon_days), local_due.date())
    while day <= last_day:
        for hour in (9, 21):
            when = _morning(day, hour)
            if now < when < local_due:
                result.append(Reminder(NotificationType.URGENT, when))
        day += timedelta(days=1)
    return result


def future_reminders(
    due_at: datetime,
    priority: TaskPriority,
    now: datetime,
    horizon_days: int = 7,
    created_at: datetime | None = None,
) -> list[Reminder]:
    reminders = standard_reminders(due_at, now)
    if priority == TaskPriority.URGENT:
        # Standard events may already be persisted outside the rolling urgent
        # window. Compare against the complete standard timetable each time.
        earliest = _morning(due_at.astimezone(MOSCOW).date(), 0) - timedelta(days=8)
        first_possible = created_at or now
        all_standard = [
            item
            for item in standard_reminders(due_at, earliest)
            if item.scheduled_at >= first_possible
        ]
        reminders.extend(
            urgent
            for urgent in urgent_reminders(due_at, now, horizon_days)
            if all(
                abs(urgent.scheduled_at - standard.scheduled_at) > timedelta(minutes=15)
                for standard in all_standard
            )
        )
    reminders.sort(key=lambda item: item.scheduled_at)
    merged: list[Reminder] = []
    for reminder in reminders:
        if merged and reminder.scheduled_at - merged[-1].scheduled_at <= timedelta(minutes=15):
            # Prefer the scheduled standard reminder over a generic urgent reminder.
            if (
                merged[-1].kind == NotificationType.URGENT
                and reminder.kind != NotificationType.URGENT
            ):
                merged[-1] = reminder
            continue
        merged.append(reminder)
    return merged


def overdue_reminders(due_at: datetime, now: datetime, horizon_days: int = 2) -> list[Reminder]:
    """Return upcoming six-hour Moscow slots, excluding the deadline's own message."""
    if due_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("Notification datetimes must be timezone aware")
    local_now = now.astimezone(MOSCOW)
    start_day = local_now.date()
    end_day = start_day + timedelta(days=horizon_days)
    result: list[Reminder] = []
    day = start_day
    while day <= end_day:
        for hour in (0, 6, 12, 18):
            when = _morning(day, hour)
            if when > now and when > due_at and when - due_at >= timedelta(minutes=15):
                result.append(Reminder(NotificationType.OVERDUE, when))
        day += timedelta(days=1)
    return result


def next_digest_time(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("Notification datetime must be timezone aware")
    local_now = now.astimezone(MOSCOW)
    for hour in (9, 20):
        slot = _morning(local_now.date(), hour)
        if slot > local_now:
            return slot
    return _morning(local_now.date() + timedelta(days=1), 9)


def notification_key(task_id: int, reminder: Reminder, due_at: datetime) -> str:
    return (
        f"task:{task_id}:due:{due_at.astimezone(UTC).isoformat()}:"
        f"{reminder.kind.value}:{reminder.scheduled_at.astimezone(UTC).isoformat()}"
    )
