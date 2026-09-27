import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, InaccessibleMessage, Message, Update, User

from app.bot.common import (
    BotTaskCardPublisher,
    RegistrationMiddleware,
    parse_date,
    parse_usernames,
    service_error,
)
from app.bot.handlers.wizard import confirm_task, start_wizard
from app.bot.handlers.wizard import router as wizard_router
from app.bot.keyboards import task_list
from app.bot.renderers import draft_card, task_card
from app.bot.states import TaskWizard
from app.domain.enums import TaskPriority, TaskStatus
from app.domain.exceptions import UserNotRegistered
from app.utils.datetime import now_moscow


class FakeState:
    def __init__(self):
        self.data = {}
        self.current = None
        self.storage = SimpleNamespace(
            redis=SimpleNamespace(set=AsyncMock(return_value=True), delete=AsyncMock())
        )

    async def clear(self):
        self.data = {}
        self.current = None

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return self.data

    async def set_state(self, state):
        self.current = state.state

    async def get_state(self):
        return self.current


def test_strict_deadline_parser():
    today = now_moscow().date()
    parsed = parse_date(today.strftime("%d.%m.%Y"))
    assert parsed.hour == 23 and parsed.minute == 59 and parsed.second == 59
    for invalid in (
        "завтра",
        "1.10.2026",
        "31.02.2027",
        (today - timedelta(days=1)).strftime("%d.%m.%Y"),
    ):
        with pytest.raises(ValueError):
            parse_date(invalid)


def test_assignees_must_be_usernames():
    assert parse_usernames("@Ivanov @PETROV @ivanov") == ["ivanov", "petrov"]
    for invalid in ("", "ivanov", "@a", "@ivanov hello"):
        with pytest.raises(ValueError):
            parse_usernames(invalid)


def test_unknown_assignee_message_is_russian():
    assert "@ivanov ещё не зарегистрирован" in service_error(
        UserNotRegistered("@ivanov is not registered")
    )


@pytest.mark.asyncio
async def test_command_title_skips_title_prompt():
    state = FakeState()
    actor = SimpleNamespace(id=45, username="author", first_name="Author", last_name=None)
    message = SimpleNamespace(chat=SimpleNamespace(id=-1001), from_user=actor, answer=AsyncMock())
    settings = SimpleNamespace(allowed_chat_id=-1001)
    users = SimpleNamespace(upsert_from_telegram=AsyncMock(return_value=SimpleNamespace(id=7)))
    await start_wizard(message, state, "Заказать значки", settings, users)
    assert state.current == TaskWizard.description_choice.state
    assert state.data["title"] == "Заказать значки"
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_assignee_message_starting_with_at_reaches_wizard(monkeypatch):
    bot = Bot(token="123456:abcdefghijklmnopqrstuvwxyzABCDE")
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(wizard_router)
    dispatcher["user_service"] = SimpleNamespace(
        resolve_assignees=AsyncMock(
            return_value=[
                SimpleNamespace(user_id=7, username="author", private_chat_started=True)
            ]
        )
    )
    monkeypatch.setattr(Bot, "get_me", AsyncMock(return_value=SimpleNamespace(username="taskbot")))
    answer = AsyncMock()
    monkeypatch.setattr(Message, "answer", answer)
    actor = User(id=45, is_bot=False, first_name="Author", username="author")
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=-1001, type="supergroup"),
        from_user=actor,
        text="@author",
    )
    state = dispatcher.fsm.get_context(bot=bot, chat_id=-1001, user_id=45)
    await state.set_state(TaskWizard.assignees)
    try:
        await dispatcher.feed_update(bot, Update(update_id=1, message=message))
        assert await state.get_state() == TaskWizard.deadline.state
        assert (await state.get_data())["assignee_user_ids"] == [7]
        answer.assert_awaited_once_with("Укажите дедлайн в формате ДД.ММ.ГГГГ.")
    finally:
        await bot.session.close()


@pytest.mark.asyncio
async def test_confirm_creates_once_from_preview():
    state = FakeState()
    today = (now_moscow().date() + timedelta(days=1)).strftime("%d.%m.%Y")
    state.data = {
        "draft_id": "abc",
        "creator_user_id": 7,
        "title": "Значки",
        "priority": "HIGH",
        "assignee_user_ids": [8, 9],
        "assignee_usernames": ["ivanov", "petrov"],
        "due_at": parse_date(today).isoformat(),
        "recurrence": None,
    }
    state.current = TaskWizard.preview.state
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=45),
        message=SimpleNamespace(answer=AsyncMock()),
        answer=AsyncMock(),
    )
    tasks = SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(id=42)))
    publisher = SimpleNamespace(publish=AsyncMock(return_value=123))
    await confirm_task(callback, state, tasks, publisher, SimpleNamespace(allowed_chat_id=-1001))
    data = tasks.create.await_args.args[0]
    assert data.assignee_user_ids == [8, 9]
    assert data.due_at.hour == 23 and data.due_at.minute == 59
    assert publisher.publish.await_count == 1
    assert state.current is None


def test_list_keyboard_limits_callback_and_draft_escapes_title():
    keyboard = task_list("tasks", "all", "due", 1, 3, [42])
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "task:42:show" in callbacks
    assert all(len(callback.encode()) <= 64 for callback in callbacks)
    due = parse_date((now_moscow().date() + timedelta(days=1)).strftime("%d.%m.%Y"))
    text = draft_card(
        {
            "title": "<bad>",
            "description": None,
            "priority": "HIGH",
            "assignee_usernames": ["ivanov"],
            "due_at": due.isoformat(),
            "recurrence": None,
        },
        "author",
    )
    assert "&lt;bad&gt;" in text


def test_card_shows_no_repeat_after_series_is_disabled():
    due = parse_date((now_moscow().date() + timedelta(days=1)).strftime("%d.%m.%Y"))
    task = SimpleNamespace(
        id=42,
        title="Задача",
        description=None,
        priority=TaskPriority.NORMAL,
        status=TaskStatus.NEW,
        due_at=due,
        created_at=now_moscow(),
        assignees=[],
        creator=None,
        recurrence_series=SimpleNamespace(is_active=False),
    )
    assert "Повторение: нет" in task_card(task)


@pytest.mark.asyncio
async def test_card_publish_reuses_saved_message_id(monkeypatch):
    class Context:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def begin(self):
            return Context()

    session = Context()
    task = SimpleNamespace(id=42, chat_id=-1001, group_message_id=123)
    repo = SimpleNamespace(get=AsyncMock(return_value=task))
    monkeypatch.setattr("app.bot.common.SqlTaskRepository", lambda *_: repo)
    bot = SimpleNamespace(send_message=AsyncMock())
    service = SimpleNamespace(session_factory=lambda: session)
    publisher = BotTaskCardPublisher(bot, service, -1001)
    assert await publisher.publish(42) == 123
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_parallel_card_refreshes_keep_newest_status(monkeypatch):
    lock = asyncio.Lock()
    task = SimpleNamespace(id=42, chat_id=-1001, group_message_id=123, status=TaskStatus.NEW)
    lock_modes = []

    class Session:
        async def __aenter__(self):
            await lock.acquire()
            return self

        async def __aexit__(self, *_args):
            lock.release()

        def begin(self):
            return Transaction()

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Repo:
        def __init__(self, _session):
            pass

        async def get(self, _task_id, *, for_update=False):
            lock_modes.append(for_update)
            return task

    first_edit_started = asyncio.Event()
    release_first_edit = asyncio.Event()
    sent = []

    async def edit(text, **_kwargs):
        sent.append(text)
        if len(sent) == 1:
            first_edit_started.set()
            await release_first_edit.wait()

    monkeypatch.setattr("app.bot.common.SqlTaskRepository", Repo)
    monkeypatch.setattr("app.bot.common.task_card", lambda item: item.status.value)
    monkeypatch.setattr("app.bot.common.card", lambda *_args: None)
    bot = SimpleNamespace(edit_message_text=edit)
    publisher = BotTaskCardPublisher(bot, SimpleNamespace(session_factory=Session), -1001)

    first = asyncio.create_task(publisher.refresh(42))
    await first_edit_started.wait()

    async def transition():
        async with Session():
            task.status = TaskStatus.IN_PROGRESS

    mutation = asyncio.create_task(transition())
    await asyncio.sleep(0)
    second = asyncio.create_task(publisher.refresh(42))
    release_first_edit.set()
    await asyncio.gather(first, mutation, second)

    assert sent == [TaskStatus.NEW.value, TaskStatus.IN_PROGRESS.value]
    assert lock_modes == [True, True]


@pytest.mark.asyncio
async def test_callback_from_other_group_is_rejected(monkeypatch):
    actor = User(id=45, is_bot=False, first_name="Author")
    message = Message(
        message_id=1, date=datetime.now(UTC), chat=Chat(id=-2000, type="supergroup"), text="card"
    )
    callback = CallbackQuery(
        id="1", from_user=actor, chat_instance="x", message=message, data="task:42:complete"
    )
    answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    users = SimpleNamespace(upsert_from_telegram=AsyncMock())
    middleware = RegistrationMiddleware(users, SimpleNamespace(allowed_chat_id=-1001))
    handler = AsyncMock()
    assert await middleware(handler, callback, {}) is None
    handler.assert_not_awaited()
    users.upsert_from_telegram.assert_not_awaited()
    answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_inaccessible_callback_is_rejected_before_handlers(monkeypatch):
    callback = CallbackQuery(
        id="old",
        from_user=User(id=45, is_bot=False, first_name="Author"),
        chat_instance="x",
        message=InaccessibleMessage(
            message_id=1, date=0, chat=Chat(id=-1001, type="supergroup")
        ),
        data="task:42:complete",
    )
    answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    users = SimpleNamespace(upsert_from_telegram=AsyncMock())
    middleware = RegistrationMiddleware(users, SimpleNamespace(allowed_chat_id=-1001))
    handler = AsyncMock()

    assert await middleware(handler, callback, {}) is None
    handler.assert_not_awaited()
    answer.assert_awaited_once()
