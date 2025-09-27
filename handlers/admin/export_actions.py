"""
Admin Export/Subtract Handlers
==============================

Цей модуль містить реалізації трьох відсутніх хендлерів для адмінських дій:

* ``admin:export_stock`` — вивантаження залишків зі складу у вигляді таблиці.
* ``admin:export_collected`` — формування зведення по всіх зібраних товарах зі списків.
* ``admin:subtract_collected`` — віднімання зібраних товарів зі складу та очищення архівів.

Хендлери використовують синхронні та асинхронні сесії SQLAlchemy для
збирання даних. Для експорту звітів застосовується модуль ``pandas``; при
відсутності залежностей використовується fallback у CSV формат.

Щоб активувати ці хендлери, імпортуйте ``router`` з цього модуля у ``bot.py``
та додайте його у ``Dispatcher``:

.. code-block:: python

    from handlers.admin.export_actions import router as admin_export_router
    dp.include_router(admin_export_router)

Автор: авто‑генератор OpenAI
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, List

import pandas as pd  # type: ignore
from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

from config import ADMIN_IDS, ARCHIVES_PATH
from database.models import Product, SavedListItem
from database.session import get_session  # type: ignore
from database.orm.products import _extract_article  # type: ignore
from database.orm.archives import orm_delete_all_saved_lists_sync  # type: ignore

# Створюємо окремий роутер та застосовуємо фільтр за ID адміністраторів
router = Router()
if ADMIN_IDS:
    router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


def _collect_stock() -> pd.DataFrame:
    """Збирає повний перелік товарів для звіту по залишках.

    Повертає DataFrame з колонками: «Відділ», «Артикул», «Назва»,
    «Кількість», «Ціна», «Сума», «Місяців без руху».
    """
    rows: List[Dict[str, object]] = []
    with get_session() as session:
        products: List[Product] = session.query(Product).all()  # type: ignore
        for product in products:
            # Кількість, ціна та місяці без руху можуть бути у вигляді рядків
            try:
                qty = float(str(product.кількість).replace(',', '.'))
            except Exception:
                qty = 0.0
            try:
                price = float(product.ціна or 0.0)
            except Exception:
                price = 0.0
            try:
                months_no_move = float(product.місяці_без_руху or 0.0)
            except Exception:
                months_no_move = 0.0
            stock_sum = qty * price
            rows.append({
                "Відділ": str(product.відділ),
                "Артикул": str(product.артикул),
                "Назва": str(product.назва or ''),
                "Кількість": qty,
                "Ціна": price,
                "Сума": stock_sum,
                "Місяців без руху": months_no_move,
            })
    return pd.DataFrame(rows)


def _collect_collected_summary() -> pd.DataFrame:
    """Агрегує кількість кожного товару зі всіх збережених списків.

    Повертає DataFrame з колонками: «Відділ», «Артикул», «Назва», «Кількість».
    Якщо списки відсутні, повертає порожній DataFrame.
    """
    aggregated: Dict[str, Dict[str, object]] = {}
    with get_session() as session:
        # Кешуємо товари за артикулом
        products_map: Dict[str, Product] = {str(p.артикул): p for p in session.query(Product).all()}  # type: ignore
        saved_items: List[SavedListItem] = session.query(SavedListItem).all()  # type: ignore
        for item in saved_items:
            article = _extract_article(item.article_name)
            if not article:
                continue
            product = products_map.get(str(article))
            if not product:
                continue
            qty = float(item.quantity or 0)
            key = str(article)
            if key not in aggregated:
                aggregated[key] = {
                    "Відділ": str(product.відділ),
                    "Артикул": key,
                    "Назва": str(product.назва or ''),
                    "Кількість": qty,
                }
            else:
                aggregated[key]["Кількість"] = float(aggregated[key]["Кількість"]) + qty
    return pd.DataFrame(list(aggregated.values()))


async def _send_dataframe_as_document(cb: types.CallbackQuery, df: pd.DataFrame,
                                      filename_prefix: str, caption: str) -> None:
    """Зберігає DataFrame в Excel/CSV та надсилає файл користувачу.

    Якщо DataFrame порожній, надсилається текстове повідомлення.
    """
    if df.empty:
        await cb.message.answer("ℹ️ Дані відсутні або списки порожні.")
        return
    export_dir = os.path.join(ARCHIVES_PATH, "exports")
    os.makedirs(export_dir, exist_ok=True)
    timestamp = time.strftime("%d-%m-%Y_%H-%M")
    xlsx_path = os.path.join(export_dir, f"{filename_prefix}_{timestamp}.xlsx")
    csv_path = os.path.join(export_dir, f"{filename_prefix}_{timestamp}.csv")
    try:
        df.to_excel(xlsx_path, index=False)
        file_path = xlsx_path
    except Exception:
        # Якщо запис у Excel неможливий, створюємо CSV
        df.to_csv(csv_path, index=False)
        file_path = csv_path
    try:
        await cb.message.answer_document(FSInputFile(file_path), caption=caption)
    except TelegramBadRequest:
        # Якщо редагування повідомлення неможливе, надсилаємо нове
        await cb.message.answer_document(FSInputFile(file_path), caption=caption)


@router.callback_query(F.data == "admin:export_stock")
async def handle_export_stock(cb: types.CallbackQuery) -> None:
    """Вивантаження залишків зі складу у файл."""
    await cb.answer()
    df = _collect_stock()
    await _send_dataframe_as_document(cb, df, "stock", "📦 Звіт по залишках сформовано")


@router.callback_query(F.data == "admin:export_collected")
async def handle_export_collected(cb: types.CallbackQuery) -> None:
    """Формує та відправляє зведення по зібраному."""
    await cb.answer()
    df = _collect_collected_summary()
    await _send_dataframe_as_document(cb, df, "collected_summary", "🗂 Звіт по зібраному сформовано")


@router.callback_query(F.data == "admin:subtract_collected")
async def handle_subtract_collected(cb: types.CallbackQuery) -> None:
    """Віднімає зібрані товари зі складу та очищує архіви."""
    await cb.answer()
    df = _collect_collected_summary()
    if df.empty:
        await cb.message.answer("ℹ️ Немає збережених списків для віднімання.")
        return
    loop = asyncio.get_running_loop()
    summary_lines: List[str] = []
    try:
        # Виконуємо транзакцію у синхронному потоці
        def subtract() -> int:
            updated_count = 0
            with get_session() as session:
                for _, row in df.iterrows():
                    dept_id = str(row["Відділ"])
                    article = str(row["Артикул"])
                    qty_to_subtract = float(row["Кількість"] or 0)
                    product: Product = session.query(Product).filter(
                        Product.dept_id == dept_id,
                        Product.article == article,
                    ).one_or_none()  # type: ignore
                    if not product:
                        summary_lines.append(f"• {dept_id}:{article}: товар не знайдено")
                        continue
                        
                    # Поточна кількість (може бути рядком)
                    try:
                        before = float(str(product.кількість).replace(',', '.'))
                    except Exception:
                        before = 0.0
                    after = before - qty_to_subtract
                    if after < 0:
                        after = 0.0
                    product.кількість = after
                    updated_count += 1
                    summary_lines.append(
                        f"• {dept_id}:{article}: {before:.2f} − {qty_to_subtract:.2f} → <b>{after:.2f}</b>"
                    )
                session.commit()
            return updated_count
        updated = await loop.run_in_executor(None, subtract)
    except Exception as exc:
        await cb.message.answer(f"❌ Помилка при відніманні зібраних залишків: {exc}")
        return
    # Очищаємо архіви
    try:
        removed = await loop.run_in_executor(None, orm_delete_all_saved_lists_sync)
    except Exception:
        removed = 0
    report = ["📉 <b>Віднято зібране зі складу</b>"]
    if updated:
        report.extend(summary_lines)
        report.append("")
        report.append(f"Успішно змінено: <b>{updated}</b> позицій.")
    else:
        report.append("Не знайдено позицій для списання.")
    report.append(f"Архіви очищено: <b>{removed}</b> списків.")
    await cb.message.answer("\n".join(report), parse_mode="HTML")