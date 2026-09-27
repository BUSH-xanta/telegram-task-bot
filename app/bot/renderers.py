import re
from datetime import datetime
from html import escape

from app.domain.enums import RecurrenceUnit, TaskPriority, TaskStatus
from app.utils.datetime import MOSCOW, now_moscow

PRIORITY_LABEL = {
    TaskPriority.LOW: "🟢 Низкий",
    TaskPriority.NORMAL: "🔵 Обычный",
    TaskPriority.HIGH: "🟠 Высокий",
    TaskPriority.URGENT: "🔴 Срочный",
}
STATUS_LABEL = {
    TaskStatus.NEW: "⚪ Новая",
    TaskStatus.IN_PROGRESS: "🔵 В работе",
    TaskStatus.WAITING_AUTHOR: "🟡 Ожидает решения автора",
    TaskStatus.COMPLETED: "✅ Выполнена",
    TaskStatus.CANCELLED: "⚫ Отменена",
}
UNIT_LABEL = {
    RecurrenceUnit.DAYS: "дней",
    RecurrenceUnit.WEEKS: "недель",
    RecurrenceUnit.MONTHS: "месяцев",
    RecurrenceUnit.YEARS: "лет",
}
LINK_PATTERN = re.compile(r"(?:https?://|tg://|t\.me/)[^\s<>]+", re.I)


def render_description(value: str | None) -> str:
    if not value:
        return ""
    result: list[str] = []
    position = 0
    for match in LINK_PATTERN.finditer(value):
        result.append(escape(value[position : match.start()]))
        url = match.group().rstrip(".,!?)")
        trailing = match.group()[len(url) :]
        href = url if url.lower().startswith(("http://", "https://", "tg://")) else "https://" + url
        result.append(f'<a href="{escape(href, quote=True)}">{escape(url)}</a>')
        result.append(escape(trailing))
        position = match.end()
    result.append(escape(value[position:]))
    return "".join(result)


def user_label(username: str | None, telegram_user_id: int | None = None) -> str:
    if username:
        return "@" + escape(username.lstrip("@"))
    if telegram_user_id is not None:
        return f'<a href="tg://user?id={telegram_user_id}">пользователь</a>'
    return "пользователь"


def date_label(value: datetime) -> str:
    return value.astimezone(MOSCOW).strftime("%d.%m.%Y, %H:%M")


def repeat_label(config: dict | None) -> str:
    if not config:
        return "нет"
    return (
        f"каждые {config['interval_value']} {UNIT_LABEL[RecurrenceUnit(config['interval_unit'])]} "
        f"до {config['end_date']}"
    )


def draft_card(data: dict, creator: str | None, creator_telegram_id: int | None = None) -> str:
    priority = TaskPriority(data["priority"])
    assignees = " ".join(user_label(name) for name in data["assignee_usernames"])
    description = render_description(data.get("description"))
    return (
        f"{PRIORITY_LABEL[priority].split()[0]} <b>Новая задача</b>\n\n"
        f"<b>{escape(data['title'])}</b>\n\n"
        f"{description + chr(10) + chr(10) if description else ''}"
        f"👤 Исполнители: {assignees}\n"
        f"📅 Дедлайн: {date_label(datetime.fromisoformat(data['due_at']))}\n"
        f"⚡ Приоритет: {PRIORITY_LABEL[priority]}\n"
        f"🔁 Повторение: {repeat_label(data.get('recurrence'))}\n"
        f"👤 Автор: {user_label(creator, creator_telegram_id)}"
    )


def task_card(task: object, creator: str | None = None, recurrence: str = "нет") -> str:
    if getattr(task, "recurrence_series", None) is not None and task.recurrence_series.is_active:
        series = task.recurrence_series
        recurrence = (
            f"каждые {series.interval_value} {UNIT_LABEL[series.interval_unit]} "
            f"до {series.end_date:%d.%m.%Y}"
        )
    status = STATUS_LABEL[task.status]
    if task.due_at < now_moscow() and task.status not in (
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
        TaskStatus.WAITING_AUTHOR,
    ):
        status = f"🔴 Просрочена\nИсходный статус: {status}"
    assignees = " ".join(
        user_label(a.user.username, a.user.telegram_user_id) for a in task.assignees
    )
    creator_id = None
    if getattr(task, "creator", None) is not None:
        creator_id = task.creator.telegram_user_id
        if creator is None:
            creator = task.creator.username
    description = render_description(task.description)
    return (
        f"{PRIORITY_LABEL[task.priority].split()[0]} <b>Задача #{task.id}</b>\n\n"
        f"<b>{escape(task.title)}</b>\n\n"
        f"{description + chr(10) + chr(10) if description else ''}"
        f"Статус: {status}\n"
        f"Приоритет: {PRIORITY_LABEL[task.priority]}\n"
        f"Исполнители: {assignees}\n"
        f"Автор: {user_label(creator, creator_id)}\n"
        f"Создана: {task.created_at.astimezone(MOSCOW):%d.%m.%Y}\n"
        f"Дедлайн: {date_label(task.due_at)}\n"
        f"Повторение: {escape(recurrence)}"
    )
