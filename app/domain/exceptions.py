class TaskBotError(Exception):
    """Base error safe to translate into a user-facing response."""


class TaskNotFound(TaskBotError):
    pass


class PermissionDenied(TaskBotError):
    pass


class InvalidTaskState(TaskBotError):
    pass


class InvalidAssignee(TaskBotError):
    pass


class UserNotRegistered(InvalidAssignee):
    pass


class UserNotInChat(InvalidAssignee):
    pass


class InvalidDeadline(TaskBotError):
    pass
