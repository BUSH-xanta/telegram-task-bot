"""Long-polling entry point; Telegram routes are registered by the UI layer."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from app.bot.setup import setup_dispatcher
from app.bot.topic import GroupTopicMiddleware
from app.config import get_settings


async def ensure_bot_admin(bot: Bot, chat_id: int) -> None:
    me = await bot.get_me()
    membership = await bot.get_chat_member(chat_id, me.id)
    if membership.status not in ("administrator", "creator"):
        raise RuntimeError("The bot must be an administrator of ALLOWED_CHAT_ID")


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    storage = RedisStorage.from_url(settings.redis_url)
    bot = Bot(token=settings.bot_token.get_secret_value())
    bot.session.middleware(
        GroupTopicMiddleware(settings.allowed_chat_id, settings.allowed_message_thread_id)
    )
    dispatcher = Dispatcher(storage=storage)
    setup_dispatcher(dispatcher, bot, settings)
    try:
        logging.info("Telegram bot starting with long polling")
        await ensure_bot_admin(bot, settings.allowed_chat_id)
        await bot.delete_webhook(drop_pending_updates=False)
        await dispatcher.start_polling(bot)
    finally:
        logging.info("Telegram bot stopping")
        await storage.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
