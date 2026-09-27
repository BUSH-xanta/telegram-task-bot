from aiogram.types import InlineKeyboardButton as Button
from aiogram.types import InlineKeyboardMarkup as Markup

from app.domain.enums import TaskStatus


def rows(*button_rows: list[tuple[str, str]]) -> Markup:
    return Markup(
        inline_keyboard=[
            [Button(text=label, callback_data=data) for label, data in row] for row in button_rows
        ]
    )


def description() -> Markup:
    return rows([("✏️ Добавить", "wiz:description:add")], [("⏭ Пропустить", "wiz:description:skip")])


def priorities(prefix: str = "wiz:priority") -> Markup:
    return rows(
        [("🟢 Низкий", f"{prefix}:LOW"), ("🔵 Обычный", f"{prefix}:NORMAL")],
        [("🟠 Высокий", f"{prefix}:HIGH"), ("🔴 Срочный", f"{prefix}:URGENT")],
    )


def repeat_choice(prefix: str = "wiz:repeat") -> Markup:
    return rows([("🔁 Да", f"{prefix}:yes"), ("Нет", f"{prefix}:no")])


def repeat_units(prefix: str = "wiz:unit") -> Markup:
    return rows(
        [("Дни", f"{prefix}:DAYS"), ("Недели", f"{prefix}:WEEKS")],
        [("Месяцы", f"{prefix}:MONTHS"), ("Годы", f"{prefix}:YEARS")],
    )


def preview() -> Markup:
    return rows(
        [("✅ Создать", "wiz:create")],
        [("✏️ Изменить", "wiz:edit"), ("❌ Отмена", "wiz:cancel")],
    )


def draft_edit() -> Markup:
    return rows(
        [("Название", "wiz:field:title"), ("Описание", "wiz:field:description")],
        [("Приоритет", "wiz:field:priority"), ("Исполнители", "wiz:field:assignees")],
        [("Дедлайн", "wiz:field:deadline"), ("Повторение", "wiz:field:recurrence")],
        [("Назад", "wiz:back")],
    )


def card(task_id: int, status: TaskStatus) -> Markup:
    active = status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
    buttons: list[list[tuple[str, str]]] = []
    if active and status == TaskStatus.NEW:
        buttons.append([("▶️ Начать", f"task:{task_id}:start")])
    if active and status != TaskStatus.WAITING_AUTHOR:
        buttons.append(
            [
                ("✅ Выполнено", f"task:{task_id}:complete"),
                ("⚠️ Не могу выполнить", f"task:{task_id}:unable"),
            ]
        )
    if active and status == TaskStatus.WAITING_AUTHOR:
        buttons.append(
            [
                ("📅 Новый дедлайн", f"task:{task_id}:deadline"),
                ("👤 Сменить исполнителя", f"task:{task_id}:assignees"),
            ]
        )
    if active:
        buttons.append(
            [("✏️ Изменить", f"task:{task_id}:edit"), ("📅 Перенести", f"task:{task_id}:deadline")]
        )
        buttons.append(
            [
                ("👤 Сменить исполнителя", f"task:{task_id}:assignees"),
                ("❌ Отменить", f"task:{task_id}:cancel"),
            ]
        )
    buttons.append([("📋 История", f"task:{task_id}:history")])
    return rows(*buttons)


FILTERS = {
    "all": "Все активные",
    "archive": "Все закрытые",
    "mine": "Мои",
    "created": "Созданные мной",
    "overdue": "Просроченные",
    "new": "Новые",
    "progress": "В работе",
    "completed": "✅ Выполненные",
    "cancelled": "⚫ Отменённые",
}
SORTS = {"due": "По дедлайну", "priority": "По приоритету", "created": "По дате создания"}


def task_list(
    kind: str,
    filter_name: str,
    sort: str,
    page: int,
    total_pages: int,
    task_ids: list[int] | None = None,
) -> Markup:
    prefix = f"list:{kind}"
    buttons: list[list[tuple[str, str]]] = []
    for task_id in task_ids or []:
        buttons.append([(f"Открыть #{task_id}", f"task:{task_id}:show")])
    if kind == "tasks":
        buttons += [
            [("Все активные", f"{prefix}:all:{sort}:0"), ("Мои", f"{prefix}:mine:{sort}:0")],
            [
                ("Созданные мной", f"{prefix}:created:{sort}:0"),
                ("Просроченные", f"{prefix}:overdue:{sort}:0"),
            ],
            [("Новые", f"{prefix}:new:{sort}:0"), ("В работе", f"{prefix}:progress:{sort}:0")],
        ]
    if kind == "archive":
        buttons.append(
            [
                ("Все", f"{prefix}:archive:{sort}:0"),
                ("✅ Выполненные", f"{prefix}:completed:{sort}:0"),
                ("⚫ Отменённые", f"{prefix}:cancelled:{sort}:0"),
            ]
        )
    buttons += [
        [(label, f"{prefix}:{filter_name}:{key}:0") for key, label in SORTS.items()],
    ]
    navigation = []
    if page > 0:
        navigation.append(("⬅️", f"{prefix}:{filter_name}:{sort}:{page - 1}"))
    navigation.append((f"Страница {page + 1}/{total_pages}", "list:noop"))
    if page + 1 < total_pages:
        navigation.append(("➡️", f"{prefix}:{filter_name}:{sort}:{page + 1}"))
    buttons.append(navigation)
    return rows(*buttons)


def admins() -> Markup:
    return rows(
        [("➕ Добавить администратора", "admin:add")],
        [("➖ Удалить администратора", "admin:remove")],
    )


def private_menu() -> Markup:
    return rows(
        [("📋 Мои задачи", "private:mine")],
        [("🔴 Просроченные", "private:overdue")],
        [("✅ Завершённые", "private:completed")],
    )


def series_warning(task_id: int) -> Markup:
    return rows(
        [("Продолжить", f"series:{task_id}:continue")], [("Отмена", f"series:{task_id}:cancel")]
    )
