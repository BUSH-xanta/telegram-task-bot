from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import RecurrenceUnit, TaskPriority, TaskStatus


class AssigneeData(BaseModel):
    user_id: int
    telegram_user_id: int
    username: str
    private_chat_started: bool = False


class RecurrenceConfig(BaseModel):
    interval_value: int = Field(gt=0)
    interval_unit: RecurrenceUnit
    end_date: date


class TaskCreateData(BaseModel):
    chat_id: int
    creator_user_id: int
    title: str = Field(min_length=1, max_length=512)
    description: str | None = None
    priority: TaskPriority
    assignee_user_ids: list[int] = Field(min_length=1)
    due_at: datetime
    recurrence: RecurrenceConfig | None = None

    @model_validator(mode="after")
    def validate_task(self) -> "TaskCreateData":
        if self.due_at.tzinfo is None:
            raise ValueError("due_at must be timezone-aware")
        if len(set(self.assignee_user_ids)) != len(self.assignee_user_ids):
            raise ValueError("assignee_user_ids must be unique")
        return self


class TaskUpdateData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = None
    priority: TaskPriority | None = None
    assignee_user_ids: list[int] | None = None
    due_at: datetime | None = None
    recurrence: RecurrenceConfig | None = None


class TaskView(BaseModel):
    id: int
    chat_id: int
    creator_user_id: int
    title: str
    description: str | None
    priority: TaskPriority
    status: TaskStatus
    due_at: datetime
    assignees: list[AssigneeData]
    created_at: datetime
    group_message_id: int | None = None
    recurrence_series_id: int | None = None
    overdue: bool = False


class NotificationData(BaseModel):
    task_id: int | None
    notification_type: str
    scheduled_at: datetime
    deduplication_key: str
