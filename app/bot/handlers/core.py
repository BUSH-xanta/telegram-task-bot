from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from app.bot import keyboards
from app.bot.handlers.lists import show_list
from app.config.settings import Settings

router = Router(name="core")


@router.message(Command("start"))
async def start_command(message: Message, user_service, settings: Settings) -> None:
    if message.chat.type == "private":
        await user_service.upsert_from_telegram(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
            private_chat_started=True,
        )
        await message.answer(
            "Личные уведомления включены. Задачи создаются в рабочей беседе.",
            reply_markup=keyboards.private_menu(),
        )
    elif message.chat.id == settings.allowed_chat_id:
        await message.answer(
            "Чтобы получать личные уведомления, откройте бота в ЛС и нажмите /start."
        )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Команды:\n/task — создать задачу в рабочей беседе\n"
        "/tasks — активные задачи\n/mytasks — мои задачи\n"
        "/archive — выполненные и отменённые\n/admins — внутренние администраторы\n"
        "/start — включить личные уведомления"
    )


@router.callback_query(F.data.startswith("private:"))
async def private_menu(callback: CallbackQuery, task_service) -> None:
    if callback.message.chat.type != "private":
        await callback.answer("Меню доступно в личных сообщениях.", show_alert=True)
        return
    selection = callback.data.split(":", 1)[1]
    kind, filter_name = {
        "mine": ("mytasks", "mine"),
        "overdue": ("tasks", "overdue"),
        "completed": ("archive", "completed"),
    }.get(selection, (None, None))
    if kind is None:
        await callback.answer("Неизвестный раздел.", show_alert=True)
        return
    await show_list(callback.message, task_service, callback.from_user.id, kind, filter_name)
    await callback.answer()


@router.chat_member()
async def member_change(
    event: ChatMemberUpdated, settings: Settings, user_service, bot: Bot
) -> None:
    if event.chat.id != settings.allowed_chat_id:
        return
    user = event.new_chat_member.user
    status = event.new_chat_member.status
    is_member = status in ("creator", "administrator", "member") or (
        status == "restricted" and bool(getattr(event.new_chat_member, "is_member", False))
    )
    await user_service.upsert_from_telegram(
        user.id,
        user.username,
        user.first_name,
        user.last_name,
        is_chat_member=is_member,
    )
    if not is_member:
        tasks = await user_service.handle_member_left(user.id)
        for task in tasks:
            await bot.send_message(
                settings.allowed_chat_id,
                f"⚠️ @{escape(user.username or user.first_name)} больше не состоит в беседе.\n"
                f"Необходимо переназначить задачу #{task.id}.\n"
                f"Автор: @{escape(task.creator.username or task.creator.first_name)}",
                parse_mode="HTML",
            )


@router.message(F.new_chat_members)
async def joined_members(message: Message, user_service, settings: Settings) -> None:
    if message.chat.id != settings.allowed_chat_id:
        return
    for user in message.new_chat_members:
        if user.is_bot:
            continue
        await user_service.upsert_from_telegram(
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            is_chat_member=True,
        )
