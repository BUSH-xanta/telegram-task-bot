"""Standalone long-running worker process."""

import asyncio
import logging

from aiogram import Bot

from app.config import get_settings
from app.db.session import make_session_factory
from app.scheduler.worker import SchedulerWorker


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    session_factory = make_session_factory(settings.database_url)
    bot = Bot(token=settings.bot_token.get_secret_value())
    worker = SchedulerWorker(session_factory, bot, settings.allowed_chat_id, settings.bot_owner_id)
    logging.info("Worker started")
    try:
        await worker.run_forever()
    finally:
        logging.info("Worker stopped")
        await bot.session.close()
        await session_factory.kw["bind"].dispose()


if __name__ == "__main__":
    asyncio.run(main())
