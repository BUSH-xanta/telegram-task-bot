from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import DeleteMessage

from app.bot.wizard_cleanup import cleanup_wizard, remember_message, wizard_answer


class State:
    def __init__(self):
        self.data = {}

    async def get_data(self):
        return self.data

    async def update_data(self, **values):
        self.data.update(values)


@pytest.mark.asyncio
async def test_tracks_only_wizard_message_ids_and_deduplicates():
    state = State()
    user_message = SimpleNamespace(chat=SimpleNamespace(id=-1001), message_id=10)
    bot_message = SimpleNamespace(chat=SimpleNamespace(id=-1001), message_id=11)
    user_message.answer = AsyncMock(return_value=bot_message)
    await remember_message(state, user_message)
    await remember_message(state, user_message)
    await wizard_answer(user_message, state, "deadline")
    bot = AsyncMock()
    assert await cleanup_wizard(state, bot)
    assert [call.args for call in bot.delete_message.await_args_list] == [(-1001, 10), (-1001, 11)]


@pytest.mark.asyncio
async def test_cleanup_continues_when_one_message_cannot_be_deleted():
    state = State()
    state.data = {"wizard_messages": [[-1001, 10], [-1001, 11]]}
    bot = AsyncMock()
    bot.delete_message.side_effect = [
        TelegramForbiddenError(
            method=DeleteMessage(chat_id=-1001, message_id=10), message="not enough rights"
        ),
        True,
    ]
    assert not await cleanup_wizard(state, bot)
    assert bot.delete_message.await_count == 2


@pytest.mark.asyncio
async def test_already_deleted_message_is_successful_cleanup():
    state = State()
    state.data = {"wizard_messages": [[-1001, 10]]}
    bot = AsyncMock()
    bot.delete_message.side_effect = TelegramBadRequest(
        method=DeleteMessage(chat_id=-1001, message_id=10), message="message to delete not found"
    )
    assert await cleanup_wizard(state, bot)
