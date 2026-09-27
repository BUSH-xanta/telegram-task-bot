from aiogram.fsm.state import State, StatesGroup


class TaskWizard(StatesGroup):
    title = State()
    description_choice = State()
    description = State()
    priority = State()
    assignees = State()
    deadline = State()
    recurrence_choice = State()
    recurrence_interval = State()
    recurrence_unit = State()
    recurrence_end = State()
    preview = State()
    edit_menu = State()


class TaskAction(StatesGroup):
    reason = State()
    deadline = State()
    assignees = State()
    edit_value = State()
    recurrence_choice = State()
    recurrence_interval = State()
    recurrence_unit = State()
    recurrence_end = State()
    series_confirm = State()


class AdminAction(StatesGroup):
    add = State()
    remove = State()
