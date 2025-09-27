# epicservice/database/orm/archives.py

import logging
import os
import shutil
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from config import ARCHIVES_PATH
from database.engine import async_session, sync_session
from database.models import (Product, SavedList, SavedListItem)
# Імпортуємо допоміжну функцію з нового модуля
from database.orm.products import _extract_article

# Налаштовуємо логер для цього модуля
logger = logging.getLogger(__name__)


# --- Асинхронні функції для роботи з архівами ---

# ВИПРАВЛЕНО: Змінено порядок аргументів для відповідності конвенції
async def orm_add_saved_list(session, user_id: int, file_name: str, file_path: str, items: list[dict]):
    """
    Додає інформацію про новий збережений список до бази даних.

    Створює запис у `SavedList` та пов'язані з ним записи у `SavedListItem`.
    Ця функція повинна виконуватися в межах існуючої транзакції.

    Args:
        session: Екземпляр асинхронної сесії SQLAlchemy.
        user_id: ID користувача, що зберіг список.
        file_name: Ім'я згенерованого Excel-файлу.
        file_path: Повний шлях до згенерованого файлу.
        items: Список словників з даними про товари для збереження.
    """
    new_list = SavedList(user_id=user_id, file_name=file_name, file_path=file_path)
    session.add(new_list)
    await session.flush()  # Отримуємо ID для new_list

    for item in items:
        list_item = SavedListItem(
            list_id=new_list.id,
            article_name=item["article_name"],
            quantity=item["quantity"],
        )
        session.add(list_item)


async def orm_update_reserved_quantity(session, items: list[dict]):
    """
    Оновлює кількість зарезервованих товарів (`відкладено`).
    """
    # для імпорту потрібна orm_get_product_by_id, але щоб уникнути
    # циклічного імпорту, простіше реалізувати логіку тут
    from database.orm.products import orm_get_product_by_id

    for item in items:
        product = await orm_get_product_by_id(
            session, item["product_id"], for_update=True
        )
        if product:
            product.відкладено = (product.відкладено or 0) + item["quantity"]


async def orm_get_user_lists_archive(user_id: int) -> list[SavedList]:
    """
    Отримує архів збережених списків для конкретного користувача.
    """
    async with async_session() as session:
        query = (
            select(SavedList)
            .where(SavedList.user_id == user_id)
            .order_by(SavedList.created_at.desc())
        )
        result = await session.execute(query)
        return result.scalars().all()


async def orm_get_all_files_for_user(user_id: int) -> list[str]:
    """
    Отримує шляхи до всіх збережених файлів-списків для користувача.
    """
    async with async_session() as session:
        query = select(SavedList.file_path).where(SavedList.user_id == user_id)
        result = await session.execute(query)
        return result.scalars().all()


async def orm_get_users_with_archives() -> list[tuple[int, int]]:
    """
    Отримує список користувачів, які мають хоча б один збережений список.
    """
    async with async_session() as session:
        query = (
            select(SavedList.user_id, func.count(SavedList.id).label("lists_count"))
            .group_by(SavedList.user_id)
            .order_by(func.count(SavedList.id).desc())
        )
        result = await session.execute(query)
        return result.all()


# --- Синхронні функції для звітів та фонових завдань ---

def orm_get_all_collected_items_sync() -> list[dict]:
    """
    Синхронно збирає зведені дані про всі товари у всіх збережених списках.
    """
    with sync_session() as session:
        all_products = {p.артикул: p for p in session.execute(select(Product)).scalars()}
        all_saved_items = session.execute(select(SavedListItem)).scalars().all()

        collected_data = {}
        for item in all_saved_items:
            article = _extract_article(item.article_name)
            if not article or article not in all_products:
                continue

            product_info = all_products[article]
            
            if article in collected_data:
                collected_data[article]["quantity"] += item.quantity
            else:
                collected_data[article] = {
                    "department": product_info.відділ,
                    "group": product_info.група,
                    "name": product_info.назва,
                    "quantity": item.quantity,
                }
        
        return list(collected_data.values())


def orm_delete_all_saved_lists_sync() -> int:
    """
    Синхронно видаляє абсолютно всі збережені списки, їхні позиції та файли.
    """
    with sync_session() as session:
        lists_count = session.execute(select(func.count(SavedList.id))).scalar_one()
        if lists_count == 0:
            return 0
        
        session.execute(delete(SavedListItem))
        session.execute(delete(SavedList))
        session.commit()
        
        if os.path.exists(ARCHIVES_PATH):
            shutil.rmtree(ARCHIVES_PATH)
        
        return lists_count


def orm_get_users_for_warning_sync(hours_warn: int, hours_expire: int) -> set[int]:
    """
    Синхронно знаходить користувачів для попередження про видалення списків.
    """
    with sync_session() as session:
        warn_time = datetime.now() - timedelta(hours=hours_warn)
        expire_time = datetime.now() - timedelta(hours=hours_expire)

        query = (
            select(SavedList.user_id)
            .where(SavedList.created_at < warn_time, SavedList.created_at > expire_time)
            .distinct()
        )
        return set(session.execute(query).scalars().all())


def orm_delete_lists_older_than_sync(hours: int) -> int:
    """
    Синхронно видаляє списки та файли, які старші за вказану кількість годин.
    """
    with sync_session() as session:
        expire_time = datetime.now() - timedelta(hours=hours)
        
        lists_to_delete = session.execute(select(SavedList).where(SavedList.created_at < expire_time)).scalars().all()
        
        if not lists_to_delete:
            return 0
            
        count = len(lists_to_delete)
        list_ids_to_delete = [lst.id for lst in lists_to_delete]
        
        for lst in lists_to_delete:
            if os.path.exists(lst.file_path):
                try:
                    os.remove(lst.file_path)
                    user_dir = os.path.dirname(lst.file_path)
                    if not os.listdir(user_dir):
                        os.rmdir(user_dir)
                except OSError as e:
                    logger.error(f"Помилка видалення архівного файлу або папки {lst.file_path}: {e}")

        session.execute(delete(SavedListItem).where(SavedListItem.list_id.in_(list_ids_to_delete)))
        session.execute(delete(SavedList).where(SavedList.id.in_(list_ids_to_delete)))
        session.commit()
        
        return count