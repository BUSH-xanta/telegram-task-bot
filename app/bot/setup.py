from aiogram import Bot, Dispatcher

from app.bot.common import BotTaskCardPublisher, RegistrationMiddleware, TelegramMembershipProvider
from app.bot.handlers import actions, admins, core, lists, wizard
from app.config.settings import Settings
from app.db.session import make_session_factory
from app.services.permission_service import PermissionService
from app.services.task_service import TaskService
from app.services.user_service import UserService


def setup_dispatcher(dispatcher: Dispatcher, bot: Bot, settings: Settings) -> None:
    session_factory = make_session_factory(settings.database_url)
    membership = TelegramMembershipProvider(bot)
    user_service = UserService(session_factory, membership, settings.allowed_chat_id)
    task_service = TaskService(
        session_factory, settings.allowed_chat_id, settings.bot_owner_id, membership
    )
    permission_service = PermissionService(session_factory, settings.bot_owner_id)
    card_publisher = BotTaskCardPublisher(bot, task_service, settings.allowed_chat_id)
    dispatcher["settings"] = settings
    dispatcher["user_service"] = user_service
    dispatcher["task_service"] = task_service
    dispatcher["permission_service"] = permission_service
    dispatcher["card_publisher"] = card_publisher
    registration = RegistrationMiddleware(user_service, settings)
    dispatcher.message.outer_middleware(registration)
    dispatcher.callback_query.outer_middleware(registration)
    dispatcher.include_routers(
        core.router, admins.router, lists.router, wizard.router, actions.router
    )
