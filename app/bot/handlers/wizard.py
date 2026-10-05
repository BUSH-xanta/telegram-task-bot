import logging
import re
from datetime import datetime
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards
from app.bot.common import (
    BotTaskCardPublisher,
    answer_action_error,
    parse_date,
    parse_usernames,
    service_error,
)
from app.bot.renderers import draft_card
from app.bot.states import TaskWizard
from app.bot.wizard_cleanup import cleanup_wizard, remember_message, wizard_answer
from app.config.settings import Settings
from app.domain.enums import RecurrenceUnit, TaskPriority
from app.domain.schemas import RecurrenceConfig, TaskCreateData
from app.utils.datetime import MOSCOW

router = Router(name="wizard")
logger = logging.getLogger(__name__)
BOT_MENTION = re.compile(r"^@([A-Za-z0-9_]+)(?:\s+(.+))?", re.S)


async def start_wizard(
    message: Message, state: FSMContext, title: str | None, settings: Settings, user_service
) -> None:
    if message.chat.id != settings.allowed_chat_id:
        await message.answer("Задачи создаются только в рабочей беседе.")
        return
    user = await user_service.upsert_from_telegram(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
        is_chat_member=True,
    )
    await cleanup_wizard(state, message.bot)
    await state.clear()
    await remember_message(state, message)
    await state.update_data(
        draft_id=uuid4().hex,
        creator_user_id=user.id,
        creator_username=message.from_user.username,
        creator_telegram_id=message.from_user.id,
    )
    if title and title.strip():
        await state.update_data(title=title.strip()[:512])
        await state.set_state(TaskWizard.description_choice)
        await wizard_answer(
            message, state, "Добавить описание?", reply_markup=keyboards.description()
        )
    else:
        await state.set_state(TaskWizard.title)
        await wizard_answer(message, state, "Новая задача\n\nНапишите название задачи.")


@router.message(Command("task"))
async def task_command(
    message: Message, command: CommandObject, state: FSMContext, settings: Settings, user_service
) -> None:
    await start_wizard(message, state, command.args, settings, user_service)


@router.message(StateFilter(None), F.text.regexp(BOT_MENTION))
async def mention_task(
    message: Message, state: FSMContext, bot: Bot, settings: Settings, user_service
) -> None:
    match = BOT_MENTION.match(message.text or "")
    me = await bot.get_me()
    if not match or match.group(1).lower() != (me.username or "").lower():
        return
    await start_wizard(message, state, match.group(2), settings, user_service)


@router.message(TaskWizard.title, F.text)
async def title_input(message: Message, state: FSMContext) -> None:
    await remember_message(state, message)
    value = message.text.strip()
    if not value or len(value) > 512:
        await wizard_answer(message, state, "Название должно содержать от 1 до 512 символов.")
        return
    await state.update_data(title=value)
    if (await state.get_data()).get("editing"):
        await show_preview(message, state)
    else:
        await state.set_state(TaskWizard.description_choice)
        await wizard_answer(
            message, state, "Добавить описание?", reply_markup=keyboards.description()
        )


@router.callback_query(F.data.startswith("wiz:description:"))
async def description_choice(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data.endswith(":add"):
        await state.set_state(TaskWizard.description)
        await wizard_answer(
            callback.message, state, "Напишите описание задачи обычным текстом или ссылкой."
        )
    else:
        await state.update_data(description=None)
        if (await state.get_data()).get("editing"):
            await show_preview(callback.message, state)
        else:
            await state.set_state(TaskWizard.priority)
            await wizard_answer(
                callback.message, state, "Выберите приоритет:", reply_markup=keyboards.priorities()
            )
    await callback.answer()


@router.message(TaskWizard.description, F.text)
async def description_input(message: Message, state: FSMContext) -> None:
    await remember_message(state, message)
    if len(message.text) > 3000:
        await wizard_answer(message, state, "Описание слишком длинное. Максимум 3000 символов.")
        return
    await state.update_data(description=message.text)
    if (await state.get_data()).get("editing"):
        await show_preview(message, state)
    else:
        await state.set_state(TaskWizard.priority)
        await wizard_answer(
            message, state, "Выберите приоритет:", reply_markup=keyboards.priorities()
        )


@router.callback_query(F.data.startswith("wiz:priority:"))
async def priority_choice(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.rsplit(":", 1)[1]
    try:
        TaskPriority(value)
    except ValueError:
        await callback.answer("Неизвестный приоритет.", show_alert=True)
        return
    await state.update_data(priority=value)
    if (await state.get_data()).get("editing"):
        await show_preview(callback.message, state)
    else:
        await state.set_state(TaskWizard.assignees)
        await wizard_answer(
            callback.message,
            state,
            "Укажите исполнителя или исполнителей через @username одним сообщением.\n"
            "Пример: @ivanov @petrov",
        )
    await callback.answer()


@router.message(TaskWizard.assignees, F.text)
async def assignees_input(message: Message, state: FSMContext, user_service) -> None:
    await remember_message(state, message)
    try:
        usernames = parse_usernames(message.text)
        assignees = await user_service.resolve_assignees(usernames)
    except ValueError as exc:
        await wizard_answer(message, state, str(exc))
        return
    except Exception as exc:
        logger.exception("Could not resolve wizard assignees")
        await wizard_answer(message, state, service_error(exc))
        return
    await state.update_data(
        assignee_user_ids=[assignee.user_id for assignee in assignees],
        assignee_usernames=[assignee.username for assignee in assignees],
        assignee_private=[assignee.private_chat_started for assignee in assignees],
    )
    for assignee in assignees:
        if not assignee.private_chat_started:
            await wizard_answer(
                message,
                state,
                f"⚠️ @{assignee.username} ещё не активировал личные уведомления. "
                "Ему необходимо открыть бота и нажать /start. "
                "Задача всё равно будет создана. Общая сводка приходит в рабочую тему "
                "в 09:00 и 20:00 МСК; отдельных напоминаний в ЛС нет.",
            )
    if (await state.get_data()).get("editing"):
        await show_preview(message, state)
    else:
        await state.set_state(TaskWizard.deadline)
        await wizard_answer(message, state, "Укажите дедлайн в формате ДД.ММ.ГГГГ.")


@router.message(TaskWizard.deadline, F.text)
async def deadline_input(message: Message, state: FSMContext) -> None:
    await remember_message(state, message)
    try:
        due_at = parse_date(message.text)
    except ValueError as exc:
        await wizard_answer(message, state, str(exc))
        return
    await state.update_data(due_at=due_at.isoformat())
    if (await state.get_data()).get("editing"):
        await show_preview(message, state)
    else:
        await state.set_state(TaskWizard.recurrence_choice)
        await wizard_answer(
            message, state, "Повторять задачу?", reply_markup=keyboards.repeat_choice()
        )


@router.callback_query(F.data.startswith("wiz:repeat:"))
async def repeat_choice(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data.endswith(":no"):
        await state.update_data(recurrence=None)
        await show_preview(callback.message, state)
    else:
        await state.set_state(TaskWizard.recurrence_interval)
        await wizard_answer(
            callback.message, state, "Введите целое положительное число — интервал повторения."
        )
    await callback.answer()


@router.message(TaskWizard.recurrence_interval, F.text)
async def interval_input(message: Message, state: FSMContext) -> None:
    await remember_message(state, message)
    if not message.text.isdecimal() or int(message.text) < 1:
        await wizard_answer(message, state, "Введите целое положительное число.")
        return
    await state.update_data(interval_value=int(message.text))
    await state.set_state(TaskWizard.recurrence_unit)
    await wizard_answer(
        message, state, "Выберите единицу интервала:", reply_markup=keyboards.repeat_units()
    )


@router.callback_query(F.data.startswith("wiz:unit:"))
async def unit_choice(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.rsplit(":", 1)[1]
    try:
        RecurrenceUnit(value)
    except ValueError:
        await callback.answer("Неизвестная единица.", show_alert=True)
        return
    await state.update_data(interval_unit=value)
    await state.set_state(TaskWizard.recurrence_end)
    await wizard_answer(
        callback.message, state, "Укажите дату окончания серии в формате ДД.ММ.ГГГГ."
    )
    await callback.answer()


@router.message(TaskWizard.recurrence_end, F.text)
async def recurrence_end_input(message: Message, state: FSMContext) -> None:
    await remember_message(state, message)
    try:
        end = parse_date(message.text).date()
    except ValueError as exc:
        await wizard_answer(message, state, str(exc))
        return
    data = await state.get_data()
    if end < datetime.fromisoformat(data["due_at"]).date():
        await wizard_answer(
            message, state, "Дата окончания серии должна быть не раньше первого дедлайна."
        )
        return
    await state.update_data(
        recurrence={
            "interval_value": data["interval_value"],
            "interval_unit": data["interval_unit"],
            "end_date": end.strftime("%d.%m.%Y"),
        }
    )
    await show_preview(message, state)


async def show_preview(message: Message, state: FSMContext) -> None:
    await state.update_data(editing=False)
    await state.set_state(TaskWizard.preview)
    data = await state.get_data()
    await wizard_answer(
        message,
        state,
        draft_card(data, data["creator_username"], data["creator_telegram_id"]),
        reply_markup=keyboards.preview(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "wiz:edit")
async def edit_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TaskWizard.edit_menu)
    await wizard_answer(
        callback.message, state, "Что изменить?", reply_markup=keyboards.draft_edit()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("wiz:field:"))
async def edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.rsplit(":", 1)[1]
    await state.update_data(editing=True)
    match field:
        case "title":
            await state.set_state(TaskWizard.title)
            await wizard_answer(callback.message, state, "Напишите новое название.")
        case "description":
            await state.set_state(TaskWizard.description_choice)
            await wizard_answer(
                callback.message, state, "Изменить описание?", reply_markup=keyboards.description()
            )
        case "priority":
            await state.set_state(TaskWizard.priority)
            await wizard_answer(
                callback.message, state, "Выберите приоритет:", reply_markup=keyboards.priorities()
            )
        case "assignees":
            await state.set_state(TaskWizard.assignees)
            await wizard_answer(callback.message, state, "Укажите исполнителей через @username.")
        case "deadline":
            await state.set_state(TaskWizard.deadline)
            await wizard_answer(callback.message, state, "Укажите дедлайн в формате ДД.ММ.ГГГГ.")
        case "recurrence":
            await state.set_state(TaskWizard.recurrence_choice)
            await wizard_answer(
                callback.message, state, "Повторять задачу?", reply_markup=keyboards.repeat_choice()
            )
    await callback.answer()


@router.callback_query(F.data == "wiz:back")
async def back_preview(callback: CallbackQuery, state: FSMContext) -> None:
    await show_preview(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "wiz:cancel")
async def cancel_wizard(callback: CallbackQuery, state: FSMContext) -> None:
    cleaned = await cleanup_wizard(state, callback.bot)
    await state.clear()
    await callback.answer(
        "Создание задачи отменено."
        if cleaned
        else "Создание отменено. Для очистки нужны права удаления сообщений.",
        show_alert=not cleaned,
    )


@router.callback_query(F.data == "wiz:create")
async def confirm_task(
    callback: CallbackQuery,
    state: FSMContext,
    task_service,
    card_publisher: BotTaskCardPublisher,
    settings: Settings,
) -> None:
    if await state.get_state() != TaskWizard.preview.state:
        await callback.answer("Этот предпросмотр уже неактивен.", show_alert=True)
        return
    data = await state.get_data()
    redis = state.storage.redis
    key = f"wizard:confirm:{callback.from_user.id}:{data['draft_id']}"
    if not await redis.set(key, "1", ex=86400, nx=True):
        await callback.answer("Задача уже создаётся или создана.")
        return
    try:
        recurrence = data.get("recurrence")
        config = None
        if recurrence:
            config = RecurrenceConfig(
                interval_value=recurrence["interval_value"],
                interval_unit=recurrence["interval_unit"],
                end_date=datetime.strptime(recurrence["end_date"], "%d.%m.%Y").date(),
            )
        create_data = TaskCreateData(
            chat_id=settings.allowed_chat_id,
            creator_user_id=data["creator_user_id"],
            title=data["title"],
            description=data.get("description"),
            priority=data["priority"],
            assignee_user_ids=data["assignee_user_ids"],
            due_at=datetime.fromisoformat(data["due_at"]).astimezone(MOSCOW),
            recurrence=config,
        )
        task = await task_service.create(create_data, callback.from_user.id)
    except Exception as exc:
        await redis.delete(key)
        await answer_action_error(callback, exc)
        return
    cleaned = await cleanup_wizard(state, callback.bot)
    await state.clear()
    await callback.answer(
        "Задача создана."
        if cleaned
        else "Задача создана. Не удалось очистить мастер: проверьте права удаления сообщений.",
        show_alert=not cleaned,
    )
    try:
        await card_publisher.publish(task.id)
    except Exception:
        logger.exception("Task %s created but card publication failed", task.id)
        await callback.message.answer(
            f"Задача #{task.id} создана, но карточку пока не удалось отправить."
        )
