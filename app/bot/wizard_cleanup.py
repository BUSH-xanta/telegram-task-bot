import logging

from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)


async def remember_message(state, message) -> None:
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    message_id = getattr(message, "message_id", None)
    if not isinstance(chat_id, int) or not isinstance(message_id, int):
        return
    data = await state.get_data()
    messages = data.get("wizard_messages", [])
    reference = [chat_id, message_id]
    if reference not in messages:
        await state.update_data(wizard_messages=[*messages, reference])


async def wizard_answer(message, state, *args, **kwargs):
    sent = await message.answer(*args, **kwargs)
    await remember_message(state, sent)
    return sent


async def cleanup_wizard(state, bot) -> bool:
    """Delete only message IDs explicitly collected by this user's wizard."""
    messages = (await state.get_data()).get("wizard_messages", [])
    failed = False
    for chat_id, message_id in messages:
        try:
            await bot.delete_message(chat_id, message_id)
        except TelegramAPIError as exc:
            if "message to delete not found" not in str(exc).lower():
                failed = True
                logger.warning("Wizard cleanup failed for message %s: %s", message_id, exc)
    return not failed
