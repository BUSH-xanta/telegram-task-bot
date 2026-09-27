from datetime import datetime
from html import escape

from app.bot.renderers import user_label
from app.db.repositories.user import SqlUserRepository
from app.domain.enums import TaskEventType
from app.utils.datetime import MOSCOW

EVENT_LABEL = {
    TaskEventType.TASK_CREATED: "создал задачу",
    TaskEventType.TASK_STARTED: "начал выполнение",
    TaskEventType.TASK_COMPLETED: "выполнил задачу",
    TaskEventType.TASK_CANCELLED: "отменил задачу",
    TaskEventType.TASK_UNABLE: "сообщил, что не может выполнить",
    TaskEventType.TASK_RESOLVED: "принял решение по задаче",
    TaskEventType.TITLE_CHANGED: "изменил название",
    TaskEventType.DESCRIPTION_CHANGED: "изменил описание",
    TaskEventType.PRIORITY_CHANGED: "изменил приоритет",
    TaskEventType.ASSIGNEES_CHANGED: "изменил исполнителей",
    TaskEventType.DEADLINE_CHANGED: "изменил дедлайн",
    TaskEventType.RECURRENCE_CHANGED: "изменил повторение",
    TaskEventType.RECURRENCE_INSTANCE_CREATED: "создал следующий экземпляр серии",
    TaskEventType.ASSIGNEE_LEFT_CHAT: "вышел из рабочей беседы",
}


def _display_value(value: object) -> str:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None:
                return parsed.astimezone(MOSCOW).strftime("%d.%m.%Y")
        except ValueError:
            pass
    text = str(value)
    return escape(text[:1000] + ("…" if len(text) > 1000 else ""))


async def render_history(task_service, task_id: int) -> list[str]:
    events = await task_service.history(task_id)
    actor_ids = {event.actor_user_id for event in events if event.actor_user_id is not None}
    actors = {}
    async with task_service.session_factory() as session:
        repo = SqlUserRepository(session)
        for actor_id in actor_ids:
            actors[actor_id] = await repo.get_by_id(actor_id)
    lines = [f"📋 <b>История задачи #{task_id}</b>"]
    for event in events:
        stamp = event.created_at.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M")
        user = actors.get(event.actor_user_id)
        actor = user_label(user.username, user.telegram_user_id) if user else "Система"
        label = EVENT_LABEL.get(event.event_type, escape(event.event_type.value))
        details = []
        payload = event.payload or {}
        if "old" in payload and "new" in payload:
            details.append(f"{_display_value(payload['old'])} → {_display_value(payload['new'])}")
        if payload.get("reason"):
            reason = str(payload["reason"])
            details.append(f"Причина: {escape(reason[:2000])}{'…' if len(reason) > 2000 else ''}")
        if payload.get("decision"):
            details.append(f"Решение: {escape(str(payload['decision']))}")
        line = f"{stamp} — {actor} {label}"
        if details:
            line += "\n" + "; ".join(details)
        lines.append(line)
    pages: list[str] = []
    current = lines[0]
    for line in lines[1:]:
        if len(current) + len(line) + 1 > 3900:
            pages.append(current)
            current = lines[0] + " (продолжение)\n" + line
        else:
            current += "\n" + line
    pages.append(current)
    return pages
