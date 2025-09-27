import logging

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL, SYNC_DATABASE_URL

# Налаштування логера для цього модуля
logger = logging.getLogger(__name__)

try:
    # --- Асинхронна частина (для роботи бота) ---
    # Створюємо асинхронний "двигун" для взаємодії з БД.
    # Цей двигун використовується в основному коді бота, що працює з asyncio.
    async_engine = create_async_engine(
        DATABASE_URL,
        echo=False,  # Встановіть True, щоб бачити всі SQL-запити в консолі (для дебагінгу)
        pool_pre_ping=True,  # Перевіряє з'єднання перед використанням, щоб уникнути помилок з'єднання
        pool_recycle=3600    # Пере-встановлює з'єднання кожну годину для стабільності
    )
    
    # Створюємо фабрику асинхронних сесій.
    # Це основний інструмент для взаємодії з БД в обробниках.
    async_session = async_sessionmaker(
        bind=async_engine,
        expire_on_commit=False, # Забороняє об'єктам "від'єднуватися" від сесії після коміту
        autoflush=False         # Вимикає автоматичний flush перед запитами
    )
    
    # --- Синхронна частина (для Alembic міграцій та скриптів) ---
    # Створюємо синхронний "двигун".
    # Він потрібен для інструментів, що не підтримують asyncio, наприклад, Alembic,
    # а також для синхронних функцій, що виконуються в окремих потоках.
    sync_engine = create_engine(
        SYNC_DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=3600
    )
    
    # Створюємо фабрику синхронних сесій.
    sync_session = sessionmaker(
        bind=sync_engine,
        autocommit=False,
        autoflush=False
    )
    
    logger.info("Підключення до бази даних (синхронне та асинхронне) успішно ініціалізовано.")
    
except Exception as e:
    logger.critical("Критична помилка ініціалізації підключення до БД: %s", e, exc_info=True)
    # Пере-викликаємо помилку, щоб зупинити запуск додатку, якщо БД недоступна
    raise