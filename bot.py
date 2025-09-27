import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand
from aiogram import Router
from sqlalchemy import text

from config import BOT_TOKEN
from database.engine import async_session, sync_engine
from database.orm.products import ensure_schema
from handlers import (archive, common, error_handler, user_search)
from handlers.admin import subtract_handlers as admin_subtract  # type: ignore
from handlers.admin import (archive_handlers as admin_archive,
                             core as admin_core,
                             import_handlers as admin_import,
                             report_handlers as admin_reports,
                             photo_admin)  # type: ignore
from handlers.user import (item_addition, list_editing, list_management,
                           list_saving, product_bridge)  # type: ignore
from middlewares.logging_middleware import LoggingMiddleware  # type: ignore

# Нове: імпортуємо хендлери карток/додавання з кешем
from handlers.user.card_handlers import open_product  # type: ignore
from handlers.user.add_handlers import add_fixed      # type: ignore

# --- Нове: імпортуємо роутер експортних хендлерів ---
from handlers.admin.export_actions import router as admin_export_router

# Спроба увімкнути «анти-глухий кут», якщо сумісний з aiogram 3.x
try:
    from utils.kb_guard import install_kb_audit
except Exception:
    install_kb_audit = None


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
        "% (asctime)s - %(levelname)s - "
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

    # Перевірка БД
    try:
        async with async_session() as session:
            await session.execute(text('SELECT 1'))
        logger.info("Підключення до бази даних успішне.")
    except Exception as e:
        logger.critical("Помилка підключення до бази даних: %s", e, exc_info=True)
        sys.exit(1)

    # --- Створення схеми БД (автоматично при першому запуску) ---
    try:
        ensure_schema(sync_engine)
        logger.info("Схема БД перевірена/створена автоматично.")
    except Exception as e:
        logger.critical("Помилка створення схеми БД: %s", e, exc_info=True)
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(
        parse_mode="Markdown",
        link_preview_is_disabled=True
    ))
    dp = Dispatcher()

    # Логування апдейтів
    dp.update.middleware(LoggingMiddleware())

    # Анти «глухий кут» (опційно, якщо доступний під v3)
    if install_kb_audit:
        try:
            install_kb_audit(dp)
            logger.info("KB-guard встановлено.")
        except Exception:
            logger.warning("KB-guard недоступний для aiogram 3.x, пропускаю.")

    # --- Реєстрація існуючих роутерів ---
    dp.include_router(error_handler.router)
    dp.include_router(admin_core.router)

    # Підключаємо модулі 2.x з функцією register(dp)
    admin_import.register(dp)
    admin_reports.register(dp)
    admin_subtract.register(dp)

    # Модулі з роутерами v3
    dp.include_router(admin_archive.router)
    dp.include_router(photo_admin.router)
    dp.include_router(common.router)
    dp.include_router(archive.router)
    dp.include_router(list_management.router)
    dp.include_router(item_addition.router)
    dp.include_router(list_editing.router)
    dp.include_router(list_saving.router)
    dp.include_router(user_search.router)
    dp.include_router(product_bridge.router)

    # Нове: Реєструємо експортні хендлери адмінки
    dp.include_router(admin_export_router)

    # Кешовані картки та швидке додавання
    cache_router = Router(name="cached_cards")
    cache_router.callback_query.register(open_product, F.data.startswith("open:"))
    cache_router.callback_query.register(add_fixed, F.data.startswith("add:"))
    dp.include_router(cache_router)

    # Старт поллінгу
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
