# -*- coding: utf-8 -*-
"""
Місток сумісності для старих колбеків "product:{id}" → нова картка через кеш.

Призначення:
- Перехопити callback "product:<product_id>" (як його генерують твої існуючі клавіатури пошуку/списків).
- Знайти у БД товар, дістати (dept_id, article) і викликати новий хендлер open_product.
- Якщо товар не знайдено — акуратно повідомити і не ламати користувачу сесію.

Залежності:
    aiogram 3.x
    database.session.get_session
    database.orm.products.Product
    handlers.user.card_handlers.open_product  (вже реалізовано)
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery

from database.session import get_session  # type: ignore
from database.orm.products import Product  # type: ignore

# імпортуємо вже готовий хендлер відкриття картки
from handlers.user.card_handlers import open_product

router = Router(name="product_bridge")


@router.callback_query(F.data.startswith("product:"))
async def product_legacy_to_cached(cb: CallbackQuery):
    """
    Перетворення "product:<id>" → "open:<dept_id>:<article>" і делегування в open_product.
    """
    try:
        _, id_str = cb.data.split(":", 1)
        pid = int(id_str)
    except Exception:
        await cb.answer("Невірний ідентифікатор товару", show_alert=True)
        return

    # Знайти товар у БД
    with get_session() as s:
        row = s.query(Product).filter(Product.id == pid).one_or_none()

    if not row:
        await cb.answer("Товар не знайдено. Можливо, його вже видалено з довідника.", show_alert=True)
        return

    # Переформуємо callback і делегуємо в існуючий обробник відкриття картки
    cb.data = f"open:{row.dept_id}:{row.article}"
    await open_product(cb)
