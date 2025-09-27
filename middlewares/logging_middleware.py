# epicservice/middlewares/logging_middleware.py

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

# Отримуємо основний логер, щоб додати до нього наш фільтр
logger = logging.getLogger(__name__)


class UserContextFilter(logging.Filter):
    """
    Фільтр для логів, що додає контекстну інформацію про користувача та оновлення.
    """
    def filter(self, record):
        # Встановлюємо значення за замовчуванням
        record.user_id = getattr(record, 'user_id', 'N/A')
        record.update_id = getattr(record, 'update_id', 'N/A')
        return True

# Додаємо фільтр до логера один раз при завантаженні модуля
if not any(isinstance(f, UserContextFilter) for f in logger.filters):
    logger.addFilter(UserContextFilter())


class LoggingMiddleware(BaseMiddleware):
    """
    Middleware для збагачення логів contextual-інформацією.

    Цей middleware витягує ID користувача та ID оновлення з кожного
    вхідного event'у (повідомлення, callback-запиту) та додає їх
    до записів у лог-файлі через `logging.LoggerAdapter`.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Визначаємо користувача з event'у
        user = data.get("event_from_user")
        user_id = user.id if user else "N/A"
        
        # Визначаємо ID оновлення
        update_id = event.update_id if hasattr(event, 'update_id') else "N/A"

        # Створюємо адаптер для логера, що додає нашу кастомну інформацію
        adapter = logging.LoggerAdapter(
            logger, {"user_id": user_id, "update_id": update_id}
        )
        
        # Передаємо адаптер у всі наступні обробники через data
        data["logger"] = adapter

        # Викликаємо наступний middleware або обробник у ланцюжку
        return await handler(event, data)