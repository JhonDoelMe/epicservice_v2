# epicservice/bot.py

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand
from sqlalchemy import text

from config import BOT_TOKEN
from database.engine import async_session
from handlers import (archive, common, error_handler, user_search)
from handlers.admin import (archive_handlers as admin_archive,
                            core as admin_core,
                            import_handlers as admin_import,
                            report_handlers as admin_reports)
from handlers.user import (item_addition, list_editing, list_management,
                           list_saving)
from middlewares.logging_middleware import LoggingMiddleware


# --- ЗМІНА: Функція для видалення меню команд ---
async def set_main_menu(bot: Bot):
    """
    Встановлює головне меню (команди) для бота.
    Передача порожнього списку видаляє меню.
    """
    await bot.set_my_commands([])


async def main():
    """
    Головна асинхронна функція для ініціалізації та запуску бота.
    """
    log_format = (
        "%(asctime)s - %(levelname)s - "
        "[User:%(user_id)s | Update:%(update_id)s] - "
        "%(name)s - %(message)s"
    )
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('bot.log', mode='a')
        ]
    )
    logger = logging.getLogger(__name__)

    if not BOT_TOKEN:
        logger.critical("Критична помилка: BOT_TOKEN не знайдено! Перевірте ваш .env файл.")
        sys.exit(1)

    try:
        async with async_session() as session:
            await session.execute(text('SELECT 1'))
        logger.info("Підключення до бази даних успішне.")
    except Exception as e:
        logger.critical("Помилка підключення до бази даних: %s", e, exc_info=True)
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(
        parse_mode="Markdown",
        link_preview_is_disabled=True
    ))
    dp = Dispatcher()

    dp.update.middleware(LoggingMiddleware())

    # --- Реєстрація роутерів ---
    dp.include_router(error_handler.router)
    dp.include_router(admin_core.router)
    dp.include_router(admin_import.router)
    dp.include_router(admin_reports.router)
    dp.include_router(admin_archive.router)
    dp.include_router(common.router)
    dp.include_router(archive.router)
    dp.include_router(list_management.router)
    dp.include_router(item_addition.router)
    dp.include_router(list_editing.router)
    dp.include_router(list_saving.router)
    dp.include_router(user_search.router)

    try:
        await set_main_menu(bot)
        await bot.delete_webhook(drop_pending_updates=True)

        logger.info("Бот запускається...")
        await dp.start_polling(bot)

    except Exception as e:
        logger.critical("Критична помилка під час роботи бота: %s", e, exc_info=True)
    finally:
        logger.info("Завершення роботи бота...")
        await bot.session.close()
        logger.info("Сесія бота закрита.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот зупинено користувачем.")
    except Exception as e:
        logging.critical("Неочікувана помилка на верхньому рівні: %s", e, exc_info=True)
        sys.exit(1)