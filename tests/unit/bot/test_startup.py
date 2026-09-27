from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.main import ensure_bot_admin


@pytest.mark.asyncio
async def test_startup_requires_bot_to_be_group_administrator():
    bot = SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(id=123)),
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
    )
    with pytest.raises(RuntimeError, match="administrator"):
        await ensure_bot_admin(bot, -1001)
    bot.get_chat_member.assert_awaited_with(-1001, 123)

    bot.get_chat_member.return_value.status = "administrator"
    await ensure_bot_admin(bot, -1001)
