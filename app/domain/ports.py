from typing import Protocol


class MembershipProvider(Protocol):
    async def is_member(self, chat_id: int, telegram_user_id: int) -> bool: ...


class TaskCardPublisher(Protocol):
    async def publish(self, task_id: int) -> int: ...

    async def refresh(self, task_id: int) -> None: ...
