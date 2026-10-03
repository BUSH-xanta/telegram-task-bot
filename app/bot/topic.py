from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import SendMessage


class GroupTopicMiddleware(BaseRequestMiddleware):
    """Route group messages from both bot and worker to the configured forum topic."""

    def __init__(self, chat_id: int, thread_id: int | None):
        self.chat_id = chat_id
        self.thread_id = thread_id

    async def __call__(self, make_request, bot, method):
        if (
            self.thread_id is not None
            and isinstance(method, SendMessage)
            and method.chat_id == self.chat_id
        ):
            method.message_thread_id = self.thread_id
        return await make_request(bot, method)
