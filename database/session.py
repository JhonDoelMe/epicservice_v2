# -*- coding: utf-8 -*-
"""
Сесійні утиліти для SQLAlchemy.

Цей модуль надає просту фабрику сесій для синхронної роботи з базою даних
через SQLAlchemy ORM. Він використовується у таких модулях, як
`handlers/admin/import_handlers.py`, `handlers/admin/report_handlers.py` та
`handlers/admin/subtract_handlers.py`, які покладаються на функцію
`get_session()` для отримання сесії.

`get_session()` повертає контекстний менеджер, що відкриває нову
сесію за допомогою `sync_session` із модуля `database.engine` і автоматично
закриває її після завершення роботи. Це замінює відсутню реалізацію
у старому коді та усуває необхідність вручну створювати файл
`database/session.py`.
"""

from contextlib import contextmanager
from typing import Iterator

from .engine import sync_session


@contextmanager
def get_session() -> Iterator[object]:
    """Отримати нову синхронну сесію SQLAlchemy як контекстний менеджер.

    Використання:

    .. code-block:: python

        from database.session import get_session

        with get_session() as session:
            # виконуємо роботу з session
            items = session.query(Product).all()

    Після виходу з контексту сесія автоматично закривається.
    """
    session = sync_session()
    try:
        yield session
    finally:
        # Закриваємо сесію, якщо вона ще відкрита
        try:
            session.close()
        except Exception:
            # Уникаємо помилок при закритті сесії
            pass