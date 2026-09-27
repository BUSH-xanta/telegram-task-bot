from app.db import (
    Base,
    models,  # noqa: F401
)


def test_required_tables() -> None:
    assert {
        "users",
        "tasks",
        "task_assignees",
        "task_events",
        "recurrence_series",
        "internal_admins",
        "scheduled_notifications",
        "notification_deliveries",
    } <= set(Base.metadata.tables)


def test_recurrence_period_is_unique() -> None:
    task = Base.metadata.tables["tasks"]
    assert any(constraint.name == "uq_task_series_due" for constraint in task.constraints)
