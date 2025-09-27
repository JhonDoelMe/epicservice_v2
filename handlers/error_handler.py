import logging
from typing import Optional, Tuple

from aiogram import Bot, Router
from aiogram.types import CallbackQuery, ErrorEvent, Message
from aiogram.types.base import UNSET

from lexicon.lexicon import LEXICON

logger = logging.getLogger(__name__)

router = Router()

def _extract_user_info(event: ErrorEvent) -> Tuple[Optional[int], str]:
    """
    Допоміжна функція для витягування інформації про користувача з об'єкта помилки.

    Намагається отримати ID чату та інформацію про користувача (ID, username)
    з `update.message` або `update.callback_query`.

    Args:
        event: Об'єкт ErrorEvent, що містить інформацію про помилку та оновлення.

    Returns:
        Кортеж, що містить (chat_id, user_info_string).
        Якщо інформацію не вдалося отримати, значення можуть бути None або 'N/A'.
    """
    update = event.update
    
    # Спробуємо отримати дані з Message
    if isinstance(update.message, Message):
        chat_id = update.message.chat.id
        if user := update.message.from_user:
            user_info = f"user_id={user.id}, username='{user.username}'"
            return chat_id, user_info
        return chat_id, "N/A"
        
    # Якщо не вийшло, спробуємо з CallbackQuery
    if isinstance(update.callback_query, CallbackQuery):
        if message := update.callback_query.message:
            chat_id = message.chat.id
        else:
            chat_id = None # У деяких випадках message може бути відсутнім
            
        if user := update.callback_query.from_user:
            user_info = f"user_id={user.id}, username='{user.username}'"
            return chat_id, user_info
        return chat_id, "N/A"

    # Якщо джерело невідоме
    return None, "N/A"

@router.errors()
async def error_handler(event: ErrorEvent, bot: Bot):
    """
    Глобальний обробник непередбачених винятків.

    Ця функція спрацьовує, коли в будь-якому іншому обробнику виникає помилка,
    яка не була перехоплена. Вона виконує дві основні задачі:
    1. Логує детальну інформацію про помилку (включно з traceback) з рівнем CRITICAL.
    2. Надсилає користувачу коректне повідомлення про те, що сталася помилка.
    """
    chat_id, user_info = _extract_user_info(event)
    
    # Логуємо помилку з максимальною деталізацією для подальшого аналізу
    logger.critical(
        "Необроблена помилка у взаємодії з %s (чат: %s): %s",
        user_info,
        chat_id or "UNKNOWN",
        event.exception,
        exc_info=True  # Дуже важливо для отримання повного стеку викликів
    )
    
    # Сповіщаємо користувача, якщо ми знаємо, куди надсилати повідомлення
    if chat_id and chat_id != UNSET:
        try:
            await bot.send_message(chat_id, LEXICON.UNEXPECTED_ERROR)
        except Exception as e:
            # Цей виняток може виникнути, якщо бот, наприклад, заблокований користувачем.
            # Логуємо це, але вже з меншим пріоритетом.
            logger.error(
                "Не вдалося відправити повідомлення про помилку користувачу %s: %s",
                chat_id, e
            )