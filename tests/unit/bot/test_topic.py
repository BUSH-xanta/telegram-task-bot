from unittest.mock import AsyncMock

import pytest
from aiogram.methods import EditMessageText, SendMessage

from app.bot.topic import GroupTopicMiddleware


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_thread", [None, 1, 30])
async def test_group_messages_route_to_configured_topic(existing_thread):
    request = AsyncMock()
    message = SendMessage(chat_id=-100123, text="task", message_thread_id=existing_thread)
    await GroupTopicMiddleware(-100123, 42)(request, None, message)
    assert message.message_thread_id == 42
    request.assert_awaited_once_with(None, message)


@pytest.mark.asyncio
async def test_private_messages_and_other_groups_keep_their_destination():
    request = AsyncMock()
    middleware = GroupTopicMiddleware(-100123, 42)
    for chat_id in (123, -100456):
        message = SendMessage(chat_id=chat_id, text="reminder")
        await middleware(request, None, message)
        assert message.message_thread_id is None


@pytest.mark.asyncio
async def test_disabled_routing_and_card_edits_are_unchanged():
    request = AsyncMock()
    message = SendMessage(chat_id=-100123, text="task", message_thread_id=30)
    await GroupTopicMiddleware(-100123, None)(request, None, message)
    assert message.message_thread_id == 30
    edit = EditMessageText(chat_id=-100123, message_id=5, text="updated")
    await GroupTopicMiddleware(-100123, 42)(request, None, edit)
    request.assert_awaited_with(None, edit)
