import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.db.models import User
from app.domain.exceptions import UserNotRegistered
from app.services import user_service as module
from app.services.user_service import UserService


class Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def begin(self):
        return self

    async def execute(self, _statement):
        return None


class Users:
    rows: list[User] = []

    def __init__(self, _session):
        pass

    async def get_by_telegram_id(self, telegram_id):
        return next((row for row in self.rows if row.telegram_user_id == telegram_id), None)

    async def get_by_username(self, username):
        return next(
            (row for row in self.rows if row.username and row.username.lower() == username.lower()),
            None,
        )

    async def clear_username_from_other_users(self, username, telegram_id):
        for row in self.rows:
            if row.telegram_user_id != telegram_id and row.username:
                if row.username.lower() == username.lower():
                    row.username = None

    async def save(self, user):
        if user not in self.rows:
            user.id = len(self.rows) + 1
            self.rows.append(user)
        return user


class Membership:
    def __init__(self, names):
        self.names = names

    async def is_member(self, _chat_id, _telegram_id):
        return True

    async def get_member_username(self, _chat_id, telegram_id):
        return self.names.get(telegram_id)


@pytest.mark.asyncio
async def test_reused_username_moves_to_current_telegram_user(monkeypatch):
    Users.rows = [
        User(id=1, telegram_user_id=101, username="Worker", first_name="Old"),
        User(id=2, telegram_user_id=102, username="worker", first_name="Duplicate"),
    ]
    monkeypatch.setattr(module, "SqlUserRepository", Users)
    service = UserService(lambda: Session(), Membership({103: "worker"}), -100)

    current = await service.upsert_from_telegram(103, "WORKER", "Current")

    assert [row.username for row in Users.rows] == [None, None, "WORKER"]
    assignees = await service.resolve_assignees(["@worker"])
    assert [(assignee.user_id, assignee.telegram_user_id) for assignee in assignees] == [
        (current.id, 103)
    ]


@pytest.mark.asyncio
async def test_stale_username_cannot_resolve_to_former_holder(monkeypatch):
    Users.rows = [User(id=1, telegram_user_id=101, username="worker", first_name="Old")]
    monkeypatch.setattr(module, "SqlUserRepository", Users)
    service = UserService(lambda: Session(), Membership({101: "newworker"}), -100)

    with pytest.raises(UserNotRegistered):
        await service.resolve_assignees(["worker"])


def test_username_index_is_unique_and_case_insensitive():
    index = next(index for index in User.__table__.indexes if index.name == "uq_users_username_ci")
    assert index.unique
    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect())).lower()
    assert "unique index" in sql and "lower(username)" in sql
