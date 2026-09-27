"""Plain-text Telegram messages for persisted notification events."""

from datetime import datetime, timedelta

from app.db.models import Task, User
from app.domain.enums import NotificationType, TaskStatus
from app.utils.datetime import MOSCOW


def user_label(user: User) -> str:
    return f"@{user.username}" if user.username else user.first_name


def reminder_text(task: Task, kind: NotificationType, users: list[User]) -> str:
    names = ", ".join(user_label(user) for user in users) or "Исполнители"
    due = task.due_at.astimezone(MOSCOW).strftime("%d.%m.%Y, %H:%M")
    if kind == NotificationType.OVERDUE:
        heading = "🔴 Задача просрочена"
    elif kind == NotificationType.URGENT:
        heading = "🔴 Срочное напоминание"
    elif kind == NotificationType.AT_DEADLINE:
        heading = "⏰ Наступил дедлайн"
    else:
        heading = "⏰ Напоминание"
    return f"{heading}\n\n{names}, задача #{task.id}:\n{task.title}\n\n📅 Дедлайн: {due} МСК"


def digest_text(tasks: list[Task], now: datetime) -> str:
    today = now.astimezone(MOSCOW).date()
    tomorrow = today + timedelta(days=1)
    active = [task for task in tasks if task.status in (TaskStatus.NEW, TaskStatus.IN_PROGRESS)]
    buckets = [
        ("🔴 Просроченные", [t for t in active if t.due_at.astimezone(MOSCOW).date() < today]),
        (
            "⏳ До конца сегодняшнего дня",
            [t for t in active if t.due_at.astimezone(MOSCOW).date() == today],
        ),
        ("📅 На завтра", [t for t in active if t.due_at.astimezone(MOSCOW).date() == tomorrow]),
    ]
    sections = ["📋 Сводка задач"]
    for title, selected in buckets:
        lines = [f"{title} — {len(selected)}"]
        for task in sorted(selected, key=lambda item: (item.due_at, item.id)):
            names = " ".join(user_label(row.user) for row in task.assignees)
            deadline = task.due_at.astimezone(MOSCOW).strftime("%d.%m.%Y")
            lines.append(f"#{task.id} {task.title}\n{names}\nДедлайн: {deadline}")
        if not selected:
            lines.append("Нет задач.")
        sections.append("\n\n".join(lines))
    message = "\n\n".join(sections)
    if len(message) > 4000:
        return message[:3950].rsplit("\n", 1)[0] + "\n… Сводка сокращена. Полный список: /tasks"
    return message
