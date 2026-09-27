import logging
import re
from datetime import datetime

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.keyboards import card
from app.bot.renderers import task_card
from app.config.settings import Settings
from app.db.repositories.task import SqlTaskRepository
from app.domain.exceptions import (
    InvalidAssignee,
    InvalidDeadline,
    InvalidTaskState,
    PermissionDenied,
    TaskBotError,
    TaskNotFound,
    UserNotInChat,
    UserNotRegistered,
)
from app.utils.datetime import due_at_moscow, now_moscow

logger = logging.getLogger(__name__)
DATE_PATTERN = re.compile(r"\d{2}\.\d{2}\.\d{4}\Z")
USERNAMES_PATTERN = re.compile(r"@([A-Za-z0-9_]{5,32})\b")


def parse_date(value: str, *, allow_today: bool = True):
    value = value.strip()
    if not DATE_PATTERN.fullmatch(value):
        raise ValueError("Укажите дату строго в формате ДД.ММ.ГГГГ.")
    try:
        day = datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError as exc:
        raise ValueError("Такой даты не существует. Укажите ДД.ММ.ГГГГ.") from exc
    if day < now_moscow().date() or (not allow_today and day == now_moscow().date()):
        raise ValueError("Дата в прошлом недопустима.")
    return due_at_moscow(day)


def parse_usernames(text: str) -> list[str]:
    tokens = text.split()
    if not tokens or any(not USERNAMES_PATTERN.fullmatch(token) for token in tokens):
        raise ValueError("Укажите исполнителей одним сообщением: @ivanov @petrov")
    return list(dict.fromkeys(token[1:].lower() for token in tokens))


def service_error(exc: Exception) -> str:
    if isinstance(exc, UserNotRegistered):
        match = re.search(r"@([A-Za-z0-9_]+)", str(exc))
        who = f"@{match.group(1)}" if match else "Пользователь"
        return (
            f"{who} ещё не зарегистрирован в боте. Попросите его написать "
            "сообщение в беседе или запустить бота через /start."
        )
    if isinstance(exc, UserNotInChat):
        return "Пользователь не состоит в рабочей беседе. Выберите другого исполнителя."
    if isinstance(exc, InvalidAssignee):
        return "Проверьте исполнителей: нужен хотя бы один участник с @username."
    if isinstance(exc, PermissionDenied):
        return "У вас нет прав для этого действия."
    if isinstance(exc, TaskNotFound):
        return "Задача не найдена."
    if isinstance(exc, InvalidDeadline):
        return "Проверьте дедлайн: укажите текущую или будущую дату."
    if isinstance(exc, InvalidTaskState):
        return "Состояние задачи уже изменилось. Откройте актуальную карточку."
    if isinstance(exc, TaskBotError):
        return str(exc) or "Действие недоступно для этой задачи."
    return "Не удалось выполнить действие. Попробуйте позже."


class RegistrationMiddleware(BaseMiddleware):
    def __init__(self, user_service, settings: Settings):
        self.user_service = user_service
        self.settings = settings

    async def __call__(self, handler, event: TelegramObject, data: dict):
        message: Message | None = event if isinstance(event, Message) else None
        callback: CallbackQuery | None = event if isinstance(event, CallbackQuery) else None
        if callback and not isinstance(callback.message, Message):
            await callback.answer("Кнопка устарела. Откройте актуальную карточку.", show_alert=True)
            return None
        if callback:
            message = callback.message
        if (
            message
            and message.chat.type != "private"
            and message.chat.id != self.settings.allowed_chat_id
        ):
            if callback:
                await callback.answer("Бот работает только в рабочей беседе.", show_alert=True)
            return None
        actor = getattr(event, "from_user", None)
        if actor and not actor.is_bot:
            private_started = bool(
                message
                and message.chat.type == "private"
                and isinstance(event, Message)
                and (event.text or "").startswith("/start")
            )
            try:
                await self.user_service.upsert_from_telegram(
                    actor.id,
                    actor.username,
                    actor.first_name,
                    actor.last_name,
                    is_chat_member=True
                    if message and message.chat.id == self.settings.allowed_chat_id
                    else None,
                    private_chat_started=private_started,
                )
            except Exception:
                logger.exception("Failed to register Telegram user %s", actor.id)
        return await handler(event, data)


class TelegramMembershipProvider:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def is_member(self, chat_id: int, telegram_user_id: int) -> bool:
        member = await self.bot.get_chat_member(chat_id, telegram_user_id)
        return member.status in ("creator", "administrator", "member") or (
            member.status == "restricted" and bool(getattr(member, "is_member", False))
        )

    async def get_member_username(self, chat_id: int, telegram_user_id: int) -> str | None:
        member = await self.bot.get_chat_member(chat_id, telegram_user_id)
        if member.status not in ("creator", "administrator", "member") and not (
            member.status == "restricted" and bool(getattr(member, "is_member", False))
        ):
            return None
        return member.user.username


class BotTaskCardPublisher:
    def __init__(self, bot: Bot, task_service, allowed_chat_id: int):
        self.bot = bot
        self.task_service = task_service
        self.allowed_chat_id = allowed_chat_id

    async def publish(self, task_id: int) -> int:
        async with self.task_service.session_factory() as session, session.begin():
            task = await SqlTaskRepository(session).get(task_id, for_update=True)
            if task is None or task.chat_id != self.allowed_chat_id:
                raise TaskNotFound(f"Task #{task_id} was not found")
            if task.group_message_id is not None:
                return task.group_message_id
            message = await self.bot.send_message(
                self.allowed_chat_id,
                task_card(task),
                reply_markup=card(task.id, task.status),
                parse_mode="HTML",
            )
            task.group_message_id = message.message_id
            return message.message_id

    async def refresh(self, task_id: int) -> None:
        # Serialize refreshes with task transitions.  Without this lock, a
        # slower edit for an earlier status can overwrite the latest card.
        async with self.task_service.session_factory() as session, session.begin():
            task = await SqlTaskRepository(session).get(task_id, for_update=True)
            if task is None or task.chat_id != self.allowed_chat_id:
                raise TaskNotFound(f"Task #{task_id} was not found")
            if not task.group_message_id:
                return
            try:
                await self.bot.edit_message_text(
                    task_card(task),
                    chat_id=self.allowed_chat_id,
                    message_id=task.group_message_id,
                    reply_markup=card(task.id, task.status),
                    parse_mode="HTML",
                )
            except TelegramBadRequest as exc:
                if "message is not modified" not in str(exc).lower():
                    logger.warning("Could not refresh task card %s: %s", task_id, exc)


async def answer_action_error(event: Message | CallbackQuery, exc: Exception) -> None:
    logger.exception("Task action failed: %s", type(exc).__name__)
    text = service_error(exc)
    if isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)
    else:
        await event.answer(text)
