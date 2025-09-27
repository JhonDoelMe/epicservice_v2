# -*- coding: utf-8 -*-
"""
Додавання товару до списку користувача:
- Швидке додавання фіксованої кількості: callback add:<dept_id>:<article>:<n>
- Кастомна кількість:           callback add_custom:<dept_id>:<article> → запитуємо число через FSM

Логіка:
- Алокація: списуємо з products.qty не більше доступного (до 0).
- Надлишки: все, що понад доступне, записуємо у picklist_overflow_items (БД не чіпаємо).
- Інвалідуємо кеш картки після змін.

Залежності:
- aiogram 2.x
- SQLAlchemy ORM: Product, PicklistItem, PicklistOverflowItem
- database.session.get_session()
- utils.card_cache.invalidate
"""

from __future__ import annotations

import re
from typing import Tuple

from aiogram import types
from aiogram.dispatcher import Dispatcher, FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ForceReply
from sqlalchemy import and_, text

from database.session import get_session  # type: ignore
from database.orm.products import Product, PicklistItem, PicklistOverflowItem  # type: ignore
from utils.card_cache import invalidate


# ------------------------------- FSM стан ------------------------------------

class AddQtyForm(StatesGroup):
    waiting_for_qty = State()  # очікуємо введення числа користувачем


# ----------------------------- База/транзакції --------------------------------

async def _apply_add(user_id: str, dept_id: str, article: str, req_qty: float) -> Tuple[float, float]:
    """
    Алокація + надлишки. Повертає (alloc, overflow).
    """
    alloc = overflow = 0.0
    with get_session() as s:
        # блокування продукту рядком
        s.execute(text("""
            SELECT id FROM products
            WHERE dept_id = :dept AND article = :art
            FOR UPDATE SKIP LOCKED
        """), {"dept": str(dept_id), "art": str(article)})

        prod = s.query(Product).filter(
            and_(Product.dept_id == str(dept_id), Product.article == str(article))
        ).one_or_none()

        if not prod:
            s.commit()
            return 0.0, req_qty  # товар відсутній у довіднику

        available = float(prod.qty or 0.0)
        req = max(0.0, float(req_qty))

        alloc = min(available, req)
        overflow = max(req - alloc, 0.0)

        # оновлення products
        prod.qty = available - alloc

        # upsert PicklistItem
        pi = s.query(PicklistItem).filter(
            and_(PicklistItem.user_id == str(user_id),
                 PicklistItem.dept_id == str(dept_id),
                 PicklistItem.article == str(article))
        ).one_or_none()
        if not pi:
            pi = PicklistItem(user_id=str(user_id), dept_id=str(dept_id), article=str(article), qty_alloc=0.0)
            s.add(pi)
        pi.qty_alloc = float(pi.qty_alloc or 0.0) + alloc

        # upsert PicklistOverflowItem
        if overflow > 0:
            po = s.query(PicklistOverflowItem).filter(
                and_(PicklistOverflowItem.user_id == str(user_id),
                     PicklistOverflowItem.dept_id == str(dept_id),
                     PicklistOverflowItem.article == str(article))
            ).one_or_none()
            if not po:
                po = PicklistOverflowItem(user_id=str(user_id), dept_id=str(dept_id), article=str(article), qty_overflow=0.0)
                s.add(po)
            po.qty_overflow = float(po.qty_overflow or 0.0) + overflow

        # інвалідувати кеш картки
        invalidate(s, dept_id, article)

        s.commit()
    return alloc, overflow


# ------------------------------ Хендлери --------------------------------------

async def add_fixed(cb: types.CallbackQuery):
    """
    Швидке додавання фіксованої кількості.
    Формат callback_data: add:<dept_id>:<article>:<n>
    """
    try:
        _, dept_id, article, qty_str = cb.data.split(":", 3)
        n = float(qty_str)
        if n <= 0:
            raise ValueError
    except Exception:
        await cb.answer("Невірний формат кількості", show_alert=True)
        return

    alloc, over = await _apply_add(str(cb.from_user.id), dept_id, article, n)
    msg = f"✅ Додано у список: {alloc:.2f}"
    if over > 0:
        msg += f"\n➕ У надлишки: {over:.2f}"
    await cb.answer(msg, show_alert=True)


async def add_custom_start(cb: types.CallbackQuery, state: FSMContext):
    """
    Старт сценарію кастомної кількості.
    Формат callback_data: add_custom:<dept_id>:<article>
    """
    try:
        _, dept_id, article = cb.data.split(":", 2)
    except Exception:
        await cb.answer("Помилка запиту", show_alert=True)
        return

    # Збережемо контекст у FSM
    await state.update_data(dept_id=str(dept_id), article=str(article))
    await AddQtyForm.waiting_for_qty.set()

    # Питаємо кількість
    await cb.message.answer(
        "Введіть кількість (ціле або десяткове число):",
        reply_markup=ForceReply(selective=True)
    )
    await cb.answer()


_QTY_RE = re.compile(r"^\s*[-+]?\d+([.,]\d+)?\s*$")


async def add_custom_receive(message: types.Message, state: FSMContext):
    """
    Приймаємо введену користувачем кількість, застосовуємо _apply_add.
    """
    data = await state.get_data()
    dept_id = data.get("dept_id")
    article = data.get("article")

    if not dept_id or not article:
        await message.reply("Сесія втрачена. Спробуйте ще раз через кнопку «Інша к-сть».")
        await state.finish()
        return

    text = (message.text or "").strip()
    if not _QTY_RE.match(text):
        await message.reply("Невірний формат. Введіть число, наприклад: 3 або 2.5")
        return

    try:
        n = float(text.replace(",", "."))
        if n <= 0:
            raise ValueError
    except Exception:
        await message.reply("Кількість має бути більшою за нуль.")
        return

    alloc, over = await _apply_add(str(message.from_user.id), str(dept_id), str(article), n)
    lines = [f"✅ Додано у список: {alloc:.2f}"]
    if over > 0:
        lines.append(f"➕ У надлишки: {over:.2f}")
    await message.reply("\n".join(lines))

    await state.finish()


# ---------------------------- Реєстрація в DP ---------------------------------

def register_add(dp: Dispatcher) -> None:
    """
    Реєстрація хендлерів додавання кількості.
    """
    dp.register_callback_query_handler(add_fixed, lambda c: c.data and c.data.startswith("add:"))
    dp.register_callback_query_handler(add_custom_start, lambda c: c.data and c.data.startswith("add_custom:"), state="*")
    dp.register_message_handler(add_custom_receive, content_types=[types.ContentType.TEXT], state=AddQtyForm.waiting_for_qty)
