import logging
import os
from typing import List

from dotenv import load_dotenv

# Налаштування логера для цього модуля
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Завантажуємо змінні оточення з файлу .env
# Функція поверне True, якщо файл .env було знайдено та завантажено.
if not load_dotenv():
    logger.warning("Файл .env не знайдено або не вдалося завантажити. Використовуються системні змінні оточення.")

def get_required_env(var_name: str) -> str:
    """
    Отримує значення обов'язкової змінної оточення.

    Args:
        var_name: Назва змінної.

    Raises:
        ValueError: Якщо змінна оточення відсутня.

    Returns:
        Значення змінної у вигляді рядка.
    """
    value = os.getenv(var_name)
    if not value:
        error_msg = f"Критична помилка: відсутня обов'язкова змінна оточення: {var_name}"
        logger.critical(error_msg)
        raise ValueError(error_msg)
    return value

# --- Конфігурація Бота ---
BOT_TOKEN = get_required_env("BOT_TOKEN")

def get_admin_ids() -> List[int]:
    """
    Безпечно парсить та повертає список ID адміністраторів зі змінної оточення.

    Очікує рядок формату 'ID1,ID2,ID3'. Ігнорує пусті значення та пробіли.
    У разі помилки формату повертає порожній список.

    Returns:
        Список цілих чисел (ID адміністраторів).
    """
    admin_ids_str = os.getenv("ADMIN_IDS", "")
    if not admin_ids_str:
        logger.warning("Змінна ADMIN_IDS не задана. Адмін-панель буде недоступна.")
        return []
    try:
        # Розділяємо рядок по комі, видаляємо пробіли і перетворюємо на числа
        return [int(admin_id.strip()) for admin_id in admin_ids_str.split(',') if admin_id.strip()]
    except ValueError as e:
        logger.warning(
            "Некоректний формат ADMIN_IDS. Перевірте ваш .env файл. "
            "Очікується числовий формат 'ID1,ID2,ID3'. Помилка: %s", e
        )
        return []

ADMIN_IDS = get_admin_ids()

# --- Конфігурація Бази Даних ---
def validate_db_port(port_str: str) -> int:
    """
    Валідує порт бази даних.

    Args:
        port_str: Порт у вигляді рядка.

    Raises:
        ValueError: Якщо порт не є числом або виходить за межі допустимого діапазону.

    Returns:
        Порт у вигляді цілого числа.
    """
    try:
        port_int = int(port_str)
        if not 1 <= port_int <= 65535:
            raise ValueError("Порт бази даних повинен бути в діапазоні від 1 до 65535.")
        return port_int
    except ValueError as e:
        logger.critical("Невірний формат порту БД: %s", e)
        raise

DB_USER = get_required_env("DB_USER")
DB_PASS = get_required_env("DB_PASS")
DB_HOST = get_required_env("DB_HOST")
DB_PORT = validate_db_port(get_required_env("DB_PORT"))
DB_NAME = get_required_env("DB_NAME")

# Формуємо URL для підключення до БД (асинхронний та синхронний варіанти)
# Асинхронний драйвер, використовується основним додатком бота
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
# Синхронний драйвер, використовується для Alembic міграцій та деяких фонових завдань
SYNC_DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# --- Конфігурація Сховища ---
# Шлях до папки, де будуть зберігатися архіви
ARCHIVES_PATH = "archives"