from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards
from app.bot.common import BotTaskCardPublisher, answer_action_error, parse_date, parse_usernames
from app.bot.history import render_history
from app.bot.renderers import date_label, task_card, user_label
from app.bot.states import TaskAction
from app.config.settings import Settings
from app.domain.enums import RecurrenceUnit, TaskPriority, TaskStatus
from app.domain.schemas import RecurrenceConfig, TaskUpdateData

router = Router(name="actions")


async def _allowed(callback: CallbackQuery, task, action: str, permission_service) -> bool:
    permission_method = {
        "edit": permission_service.can_edit,
        "deadline": permission_service.can_reschedule,
        "assignees": permission_service.can_change_assignees,
        "cancel": permission_service.can_cancel,
    }.get(action)
    if permission_method and not await permission_method(task, callback.from_user.id):
        await callback.answer("У вас нет прав для этого действия.", show_alert=True)
        return False
    return True


async def _send_prompt(message: Message, state: FSMContext, task_id: int, action: str) -> None:
    await state.update_data(task_id=task_id, action=action)
    if action in ("unable", "cancel"):
        await state.set_state(TaskAction.reason)
        await message.answer(
            "Укажите причину, по которой задача не может быть выполнена."
            if action == "unable"
            else "Укажите причину отмены задачи."
        )
    elif action == "deadline":
        await state.set_state(TaskAction.deadline)
        await message.answer("Укажите новый дедлайн в формате ДД.ММ.ГГГГ.")
    elif action == "assignees":
        await state.set_state(TaskAction.assignees)
        await message.answer("Укажите новых исполнителей через @username одним сообщением.")
    elif action == "edit":
        await message.answer(
            "Что изменить?",
            reply_markup=keyboards.rows(
                [
                    ("Название", f"edit:{task_id}:title"),
                    ("Описание", f"edit:{task_id}:description"),
                ],
                [
                    ("Приоритет", f"edit:{task_id}:priority"),
                    ("Исполнители", f"edit:{task_id}:assignees"),
                ],
                [
                    ("Дедлайн", f"edit:{task_id}:deadline"),
                    ("Повторение", f"edit:{task_id}:recurrence"),
                ],
            ),
        )


@router.callback_query(F.data.startswith("task:"))
async def task_action(
    callback: CallbackQuery,
    state: FSMContext,
    task_service,
    permission_service,
    card_publisher: BotTaskCardPublisher,
    bot: Bot,
    settings: Settings,
) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[1].isdecimal():
        await callback.answer("Некорректная кнопка.", show_alert=True)
        return
    task_id, action = int(parts[1]), parts[2]
    try:
        task = await task_service.get(task_id)
        if action == "show":
            await callback.message.answer(
                task_card(task),
                reply_markup=keyboards.card(task.id, task.status),
                parse_mode="HTML",
            )
        elif action == "history":
            for page in await render_history(task_service, task_id):
                await callback.message.answer(page, parse_mode="HTML")
        elif action == "start":
            await task_service.start(task_id, callback.from_user.id)
            await card_publisher.refresh(task_id)
        elif action == "complete":
            if task.status == TaskStatus.COMPLETED:
                await callback.answer("Задача уже выполнена.")
                return
            await task_service.complete(task_id, callback.from_user.id)
            await card_publisher.refresh(task_id)
            if await state.storage.redis.set(
                f"task:completed:notice:{task_id}", "1", nx=True, ex=86400
            ):
                await bot.send_message(
                    settings.allowed_chat_id,
                    f"✅ Задача #{task_id} выполнена "
                    f"{user_label(callback.from_user.username, callback.from_user.id)}",
                    parse_mode="HTML",
                )
        elif action in {"unable", "cancel", "deadline", "assignees", "edit"}:
            if action != "unable" and not await _allowed(
                callback, task, action, permission_service
            ):
                return
            if action == "unable" and not any(
                item.user.telegram_user_id == callback.from_user.id for item in task.assignees
            ):
                await callback.answer("Это действие доступно исполнителю.", show_alert=True)
                return
            if task.recurrence_series_id and action in {"deadline", "assignees", "edit"}:
                await state.update_data(task_id=task_id, action=action)
                await state.set_state(TaskAction.series_confirm)
                await callback.message.answer(
                    "⚠️ Это повторяющаяся задача. Изменения также будут применены "
                    "ко всем будущим задачам этой серии.",
                    reply_markup=keyboards.series_warning(task_id),
                )
            else:
                await _send_prompt(callback.message, state, task_id, action)
        else:
            await callback.answer("Неизвестное действие.", show_alert=True)
            return
    except Exception as exc:
        await answer_action_error(callback, exc)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("series:"))
async def series_decision(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[1].isdecimal():
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    data = await state.get_data()
    if data.get("task_id") != int(parts[1]):
        await callback.answer("Действие устарело.", show_alert=True)
        return
    if parts[2] == "cancel":
        await state.clear()
        await callback.message.answer("Изменение отменено.")
    else:
        await state.update_data(series_confirmed_task_id=int(parts[1]))
        await _send_prompt(callback.message, state, int(parts[1]), data["action"])
    await callback.answer()


@router.message(TaskAction.reason, F.text)
async def reason_input(
    message: Message,
    state: FSMContext,
    task_service,
    card_publisher: BotTaskCardPublisher,
    bot: Bot,
    settings: Settings,
) -> None:
    reason = message.text.strip()
    if not reason:
        await message.answer("Причина не может быть пустой.")
        return
    data = await state.get_data()
    task_id, action = data["task_id"], data["action"]
    try:
        if action == "unable":
            task = await task_service.unable(task_id, message.from_user.id, reason)
            await bot.send_message(
                settings.allowed_chat_id,
                f"⚠️ {user_label(message.from_user.username)} сообщил, что задача #{task_id} "
                f"не может быть выполнена.\nПричина: {escape(reason)}",
                reply_markup=keyboards.rows(
                    [("📅 Новый дедлайн", f"task:{task_id}:deadline")],
                    [("👤 Сменить исполнителя", f"task:{task_id}:assignees")],
                    [("❌ Отменить задачу", f"task:{task_id}:cancel")],
                ),
                parse_mode="HTML",
            )
            if task.creator.private_chat_started:
                try:
                    await bot.send_message(
                        task.creator.telegram_user_id,
                        f"Задача #{task_id} ожидает вашего решения. Причина: {reason}",
                    )
                except Exception:
                    pass
        else:
            previous = await task_service.get(task_id)
            await task_service.cancel(task_id, message.from_user.id, reason)
            if previous.status != TaskStatus.CANCELLED and await state.storage.redis.set(
                f"task:cancelled:notice:{task_id}", "1", nx=True, ex=86400
            ):
                await bot.send_message(
                    settings.allowed_chat_id,
                    f"⚫ Задача #{task_id} отменена. Причина: {escape(reason)}",
                    parse_mode="HTML",
                )
        await card_publisher.refresh(task_id)
    except Exception as exc:
        await answer_action_error(message, exc)
        return
    await state.clear()
    await message.answer("Готово.")


@router.message(TaskAction.deadline, F.text)
async def deadline_input(
    message: Message,
    state: FSMContext,
    task_service,
    card_publisher: BotTaskCardPublisher,
    bot: Bot,
    settings: Settings,
) -> None:
    try:
        new_due = parse_date(message.text)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    data = await state.get_data()
    task_id = data["task_id"]
    try:
        old = await task_service.get(task_id)
        old_due = old.due_at
        await task_service.resolve_deadline(task_id, message.from_user.id, new_due)
        await card_publisher.refresh(task_id)
        await bot.send_message(
            settings.allowed_chat_id,
            f"📅 Дедлайн задачи #{task_id} изменён\n"
            f"Было: {date_label(old_due)}\nСтало: {date_label(new_due)}\n"
            f"Изменил: {user_label(message.from_user.username)}",
            parse_mode="HTML",
        )
    except Exception as exc:
        await answer_action_error(message, exc)
        return
    await state.clear()
    await message.answer("Дедлайн изменён.")


@router.message(TaskAction.assignees, F.text)
async def assignees_input(
    message: Message,
    state: FSMContext,
    user_service,
    task_service,
    card_publisher: BotTaskCardPublisher,
) -> None:
    try:
        assignees = await user_service.resolve_assignees(parse_usernames(message.text))
        task_id = (await state.get_data())["task_id"]
        await task_service.replace_assignees(
            task_id, message.from_user.id, [assignee.user_id for assignee in assignees]
        )
        await card_publisher.refresh(task_id)
    except Exception as exc:
        await answer_action_error(message, exc)
        return
    for assignee in assignees:
        if not assignee.private_chat_started:
            await message.answer(
                f"⚠️ @{assignee.username} ещё не активировал ЛС. "
                "Попросите его запустить бота командой /start."
            )
    await state.clear()
    await message.answer("Исполнители изменены. Статус задачи: ⚪ Новая.")


@router.callback_query(F.data.startswith("edit:"))
async def edit_field(
    callback: CallbackQuery, state: FSMContext, task_service, permission_service
) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[1].isdecimal():
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    task_id, field = int(parts[1]), parts[2]
    task = await task_service.get(task_id)
    if not await _allowed(callback, task, "edit", permission_service):
        return
    if (
        task.recurrence_series_id
        and (await state.get_data()).get("series_confirmed_task_id") != task_id
    ):
        await state.update_data(task_id=task_id, action="edit")
        await state.set_state(TaskAction.series_confirm)
        await callback.message.answer(
            "⚠️ Это повторяющаяся задача. Изменения также будут применены "
            "ко всем будущим задачам этой серии.",
            reply_markup=keyboards.series_warning(task_id),
        )
        await callback.answer()
        return
    if field in {"assignees", "deadline"}:
        await _send_prompt(callback.message, state, task_id, field)
    elif field == "priority":
        await state.update_data(task_id=task_id, action="priority")
        await callback.message.answer(
            "Выберите новый приоритет:", reply_markup=keyboards.priorities(f"editprio:{task_id}")
        )
    elif field == "recurrence":
        await state.update_data(task_id=task_id, action="recurrence")
        await state.set_state(TaskAction.recurrence_choice)
        await callback.message.answer(
            "Повторять задачу?", reply_markup=keyboards.repeat_choice(f"editrepeat:{task_id}")
        )
    elif field in {"title", "description"}:
        await state.update_data(task_id=task_id, action=field)
        await state.set_state(TaskAction.edit_value)
        await callback.message.answer(
            "Напишите новое название."
            if field == "title"
            else "Напишите новое описание. Для очистки отправьте -"
        )
    else:
        await callback.answer("Неизвестное поле.", show_alert=True)
        return
    await callback.answer()


@router.message(TaskAction.edit_value, F.text)
async def edit_text_input(
    message: Message, state: FSMContext, task_service, card_publisher: BotTaskCardPublisher
) -> None:
    data = await state.get_data()
    field, task_id = data["action"], data["task_id"]
    value = message.text.strip()
    if field == "title" and not value:
        await message.answer("Название не может быть пустым.")
        return
    if field == "description" and len(value) > 3000:
        await message.answer("Описание слишком длинное. Максимум 3000 символов.")
        return
    try:
        update = TaskUpdateData(
            **{field: None if field == "description" and value == "-" else value}
        )
        await task_service.update_task(task_id, message.from_user.id, update)
        await card_publisher.refresh(task_id)
    except Exception as exc:
        await answer_action_error(message, exc)
        return
    await state.clear()
    await message.answer("Задача изменена.")


@router.callback_query(F.data.startswith("editprio:"))
async def edit_priority(
    callback: CallbackQuery, state: FSMContext, task_service, card_publisher: BotTaskCardPublisher
) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[1].isdecimal():
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    task = await task_service.get(int(parts[1]))
    if (
        task.recurrence_series_id
        and (await state.get_data()).get("series_confirmed_task_id") != task.id
    ):
        await state.update_data(task_id=task.id, action="edit")
        await state.set_state(TaskAction.series_confirm)
        await callback.message.answer(
            "⚠️ Это повторяющаяся задача. Изменения также будут применены "
            "ко всем будущим задачам этой серии.",
            reply_markup=keyboards.series_warning(task.id),
        )
        await callback.answer()
        return
    try:
        priority = TaskPriority(parts[2])
        await task_service.update_task(
            int(parts[1]), callback.from_user.id, TaskUpdateData(priority=priority)
        )
        await card_publisher.refresh(int(parts[1]))
    except Exception as exc:
        await answer_action_error(callback, exc)
        return
    await callback.answer("Приоритет изменён.")


@router.callback_query(F.data.startswith("editrepeat:"))
async def repeat_choice(
    callback: CallbackQuery, state: FSMContext, task_service, card_publisher: BotTaskCardPublisher
) -> None:
    task_id = int(callback.data.split(":")[1])
    task = await task_service.get(task_id)
    if (
        task.recurrence_series_id
        and (await state.get_data()).get("series_confirmed_task_id") != task_id
    ):
        await state.update_data(task_id=task_id, action="edit")
        await state.set_state(TaskAction.series_confirm)
        await callback.message.answer(
            "⚠️ Это повторяющаяся задача. Изменения также будут применены "
            "ко всем будущим задачам этой серии.",
            reply_markup=keyboards.series_warning(task_id),
        )
        await callback.answer()
        return
    if callback.data.endswith(":no"):
        try:
            await task_service.update_task(
                task_id, callback.from_user.id, TaskUpdateData(recurrence=None)
            )
            await card_publisher.refresh(task_id)
        except Exception as exc:
            await answer_action_error(callback, exc)
            return
        await state.clear()
        await callback.answer("Повторение выключено.")
    else:
        await state.update_data(task_id=task_id)
        await state.set_state(TaskAction.recurrence_interval)
        await callback.message.answer("Введите целое положительное число — интервал повторения.")
        await callback.answer()


@router.message(TaskAction.recurrence_interval, F.text)
async def repeat_interval(message: Message, state: FSMContext) -> None:
    if not message.text.isdecimal() or int(message.text) < 1:
        await message.answer("Введите целое положительное число.")
        return
    await state.update_data(interval_value=int(message.text))
    await state.set_state(TaskAction.recurrence_unit)
    await message.answer("Выберите единицу:", reply_markup=keyboards.repeat_units("editunit"))


@router.callback_query(F.data.startswith("editunit:"))
async def repeat_unit(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":")[1]
    try:
        RecurrenceUnit(value)
    except ValueError:
        await callback.answer("Неверная единица.", show_alert=True)
        return
    await state.update_data(interval_unit=value)
    await state.set_state(TaskAction.recurrence_end)
    await callback.message.answer("Укажите дату окончания серии ДД.ММ.ГГГГ.")
    await callback.answer()


@router.message(TaskAction.recurrence_end, F.text)
async def repeat_end(
    message: Message, state: FSMContext, task_service, card_publisher: BotTaskCardPublisher
) -> None:
    try:
        end = parse_date(message.text).date()
        data = await state.get_data()
        task = await task_service.get(data["task_id"])
        if end < task.due_at.date():
            await message.answer("Дата окончания должна быть не раньше дедлайна.")
            return
        config = RecurrenceConfig(
            interval_value=data["interval_value"], interval_unit=data["interval_unit"], end_date=end
        )
        await task_service.update_task(
            task.id, message.from_user.id, TaskUpdateData(recurrence=config)
        )
        await card_publisher.refresh(task.id)
    except Exception as exc:
        await answer_action_error(message, exc)
        return
    await state.clear()
    await message.answer("Повторение изменено.")
