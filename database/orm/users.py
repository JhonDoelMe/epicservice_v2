# epicservice/database/orm/users.py

import logging
from typing import List

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database.engine import async_session, sync_session
from database.models import User

logger = logging.getLogger(__name__)


async def orm_upsert_user(
    user_id: int,
    username: str | None,
    first_name: str,
):
    """
    Додає нового користувача або оновлює дані існуючого.

    Використовує конструкцію INSERT ... ON CONFLICT (UPSERT),
    специфічну для PostgreSQL, для атомарного виконання операції.

    Args:
        user_id: ID користувача.
        username: Його @username (може бути відсутнім).
        first_name: Його ім'я.
    """
    async with async_session() as session:
        stmt = insert(User).values(
            id=user_id,
            username=username,
            first_name=first_name
        )
        # Якщо користувач з таким ID вже існує, оновлюємо його дані
        stmt = stmt.on_conflict_do_update(
            index_elements=['id'],
            set_={'username': username, 'first_name': first_name}
        )
        await session.execute(stmt)
        await session.commit()


def orm_get_all_users_sync() -> List[int]:
    """
    Синхронно отримує ID всіх зареєстрованих користувачів для розсилки.

    Returns:
        Список всіх унікальних user_id з таблиці users.
    """
    with sync_session() as session:
        query = select(User.id)
        return list(session.execute(query).scalars().all())