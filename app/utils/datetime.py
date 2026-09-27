from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")


def now_moscow() -> datetime:
    return datetime.now(MOSCOW)


def due_at_moscow(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59), tzinfo=MOSCOW)


def utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Naive datetime is not allowed")
    return value.astimezone(UTC)
