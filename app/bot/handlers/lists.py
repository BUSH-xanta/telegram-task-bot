from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards
from app.bot.common import answer_action_error
from app.bot.renderers import date_label
from app.config.settings import Settings
from app.domain.enums import TaskStatus
from app.utils.datetime import now_moscow

router = Router(name="lists")
TITLES = {"tasks": "📋 Задачи", "mytasks": "📋 Ваши задачи", "archive": "📋 Архив"}
PRIORITY_ICONS = {"LOW": "🟢", "NORMAL": "🔵", "HIGH": "🟠", "URGENT": "🔴"}


async def show_list(
    message: Message,
    task_service,
    actor_id: int,
    kind: str,
    filter_name: str,
    sort: str = "due",
    page: int = 0,
    *,
    edit: bool = False,
) -> None:
    if kind not in TITLES or filter_name not in keyboards.FILTERS or sort not in keyboards.SORTS:
        return
    try:
        tasks, total = await task_service.list_tasks(
            filter="active" if filter_name == "all" else filter_name,
            actor_telegram_id=actor_id,
            sort=sort,
            page=page + 1,
        )
    except Exception as exc:
        await answer_action_error(message, exc)
        return
    total_pages = max(1, (total + 9) // 10)
    if page >= total_pages:
        page = total_pages - 1
        tasks, total = await task_service.list_tasks(
            filter="active" if filter_name == "all" else filter_name,
            actor_telegram_id=actor_id,
            sort=sort,
            page=page + 1,
        )
    lines = [f"<b>{TITLES[kind]}</b> · {escape(keyboards.FILTERS[filter_name])}"]
    if not tasks:
        lines.append("\nНет задач.")
    for task in tasks:
        icon = (
            "🔴"
            if task.due_at < now_moscow()
            and task.status
            not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.WAITING_AUTHOR)
            else PRIORITY_ICONS[task.priority.value]
        )
        assignees = " ".join(
            "@" + escape(a.user.username or a.user.first_name) for a in task.assignees
        )
        lines.append(
            f"\n{icon} <b>#{task.id} {escape(task.title)}</b>\n"
            f"{assignees}\nДедлайн: {date_label(task.due_at)}"
        )
    text = "\n".join(lines)
    markup = keyboards.task_list(
        kind, filter_name, sort, page, total_pages, [task.id for task in tasks]
    )
    if edit:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.message(Command("tasks"))
async def tasks_command(message: Message, task_service, settings: Settings) -> None:
    if message.chat.id != settings.allowed_chat_id:
        await message.answer("Список задач доступен в рабочей беседе.")
        return
    await show_list(message, task_service, message.from_user.id, "tasks", "all")


@router.message(Command("mytasks"))
async def mytasks_command(message: Message, task_service) -> None:
    await show_list(message, task_service, message.from_user.id, "mytasks", "mine")


@router.message(Command("archive"))
async def archive_command(message: Message, task_service) -> None:
    await show_list(message, task_service, message.from_user.id, "archive", "archive")


@router.callback_query(F.data.startswith("list:"))
async def list_callback(callback: CallbackQuery, task_service) -> None:
    if callback.data == "list:noop":
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("Список устарел.", show_alert=True)
        return
    _, kind, filter_name, sort, page_text = parts
    try:
        page = int(page_text)
        if page < 0:
            raise ValueError
    except ValueError:
        await callback.answer("Неверная страница.", show_alert=True)
        return
    await show_list(
        callback.message,
        task_service,
        callback.from_user.id,
        kind,
        filter_name,
        sort,
        page,
        edit=True,
    )
    await callback.answer()
