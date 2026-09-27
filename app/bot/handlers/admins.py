from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards
from app.bot.common import answer_action_error
from app.bot.renderers import user_label
from app.bot.states import AdminAction
from app.config.settings import Settings

router = Router(name="admins")


async def show_admins(
    message: Message, permission_service, actor_id: int, settings: Settings
) -> None:
    admins = await permission_service.list_admins(actor_id)
    entries = [
        f"{user_label(user.username, user.telegram_user_id)} — {user.telegram_user_id}"
        for user in admins
    ]
    if not entries:
        entries = [f"Владелец — {settings.bot_owner_id}"]
    remove_buttons = [
        [(f"➖ {user.username or user.telegram_user_id}", f"admin:remove:{user.telegram_user_id}")]
        for user in admins
        if user.telegram_user_id != settings.bot_owner_id
    ]
    markup = keyboards.rows(
        [("➕ Добавить администратора", "admin:add")],
        [("➖ Удалить администратора", "admin:remove")],
        *remove_buttons,
    )
    await message.answer(
        "Внутренние администраторы:\n" + "\n".join(entries), reply_markup=markup, parse_mode="HTML"
    )


@router.message(Command("admins"))
async def admins_command(message: Message, permission_service, settings: Settings) -> None:
    try:
        await show_admins(message, permission_service, message.from_user.id, settings)
    except Exception as exc:
        await answer_action_error(message, exc)


@router.callback_query(F.data.startswith("admin:"))
async def admin_callback(
    callback: CallbackQuery, state: FSMContext, permission_service, settings: Settings
) -> None:
    if not await permission_service.can_manage_admins(callback.from_user.id):
        await callback.answer("У вас нет прав управлять администраторами.", show_alert=True)
        return
    parts = callback.data.split(":")
    if parts[1] == "add":
        await state.set_state(AdminAction.add)
        await callback.message.answer("Введите Telegram User ID нового администратора.")
    elif parts[1] == "remove" and len(parts) == 2:
        await state.set_state(AdminAction.remove)
        await callback.message.answer("Введите Telegram User ID администратора для удаления.")
    elif parts[1] == "remove" and len(parts) == 3 and parts[2].isdecimal():
        try:
            await permission_service.remove_admin(callback.from_user.id, int(parts[2]))
        except Exception as exc:
            await answer_action_error(callback, exc)
            return
        await callback.message.answer("Администратор удалён.")
    await callback.answer()


@router.message(AdminAction.add, F.text)
@router.message(AdminAction.remove, F.text)
async def admin_id_input(message: Message, state: FSMContext, permission_service) -> None:
    if not message.text.isdecimal():
        await message.answer("Введите числовой Telegram User ID.")
        return
    try:
        if await state.get_state() == AdminAction.add.state:
            user = await permission_service.add_admin(message.from_user.id, int(message.text))
            await message.answer(
                f"Добавлен администратор {user_label(user.username, user.telegram_user_id)}.",
                parse_mode="HTML",
            )
        else:
            await permission_service.remove_admin(message.from_user.id, int(message.text))
            await message.answer("Администратор удалён.")
    except Exception as exc:
        await answer_action_error(message, exc)
        return
    await state.clear()
