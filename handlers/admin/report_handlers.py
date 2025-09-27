# -*- coding: utf-8 -*-
"""
Адмінські звіти та експорт таблиць.

Функціонал:
- Звіти по відділах:
    • кількість УНІКАЛЬНИХ артикулів
    • сумарна кількість (шт) та оціночна сума (qty * price), за бажанням
    • середня/медіанна ціна (опційно)
- Експорт у .xlsx/.ods/.csv з єдиним API.
- Іменування файлів:
    report_<тип>_<dept|all>_<ДД.ММ.РРРР_ГГ.ММ>.<ext>
- Ретеншн: підчищення старих файлів з каталогу exports/.
- Експорт користувацьких списків і «надлишків» використовують інший модуль,
  але тут залишено хелпер на випадок адмінського формування.

Залежності:
- aiogram 2.x (для хендлерів)
- pandas
- SQLAlchemy ORM: Product
- utils.io_spreadsheet: write_table
- python-dotenv
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
from aiogram import types
from aiogram.dispatcher import Dispatcher
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from sqlalchemy import and_

from database.orm.products import Product  # type: ignore
from database.session import get_session  # type: ignore

from utils.io_spreadsheet import write_table

load_dotenv(override=True)

# ------------------------------ Конфіг ---------------------------------------

EXPORTS_DIR = Path(os.getenv("EXPORTS_DIR", "exports")).resolve()
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Ретеншн у днях (0 або від’ємне — не чистити)
EXPORTS_RETENTION_DAYS = int(os.getenv("EXPORTS_RETENTION_DAYS", "30") or 0)

# Дозволені формати експорту
ALLOWED_EXPORT_EXT = ("xlsx", "ods", "csv")

# Хто може викликати звіти (якщо логіка прав спрощена)
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit())


# ------------------------------ Хелпери --------------------------------------

def _ts_str() -> str:
    return time.strftime("%d.%m.%Y_%H.%M")


def _ensure_ext(ext: str) -> str:
    e = ext.lower().lstrip(".")
    if e not in ALLOWED_EXPORT_EXT:
        return "xlsx"
    return e


def _report_filename(kind: str, dept: Optional[str], ext: str) -> Path:
    """
    report_<тип>_<dept|all>_<ДД.ММ.РРРР_ГГ.ММ>.<ext>
    kind: "unique", "stock", "inactive", "all_departments" і т.п.
    """
    tag = str(dept) if dept else "all"
    name = f"report_{kind}_{tag}_{_ts_str()}.{_ensure_ext(ext)}"
    return EXPORTS_DIR / name


def _cleanup_old_exports(retention_days: int = EXPORTS_RETENTION_DAYS) -> int:
    """
    Видалити файли старше retention_days з каталогу exports/.
    Повертає кількість видалених файлів.
    """
    if retention_days <= 0:
        return 0
    import datetime as dt
    now = dt.datetime.now()
    removed = 0
    for p in EXPORTS_DIR.glob("*.*"):
        try:
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime)
            if (now - mtime).days > retention_days:
                p.unlink(missing_ok=True)
                removed += 1
        except Exception:
            # не критично
            pass
    return removed


def _df_unique_articles(products: Iterable[Product]) -> pd.DataFrame:
    """
    Повертає DataFrame з унікальними артикулами (dept_id, article, name, qty, price, sum).
    Кількість унікальних артикулів рахується по (dept_id, article).
    """
    rows: List[Dict[str, object]] = []
    for p in products:
        qty = float(getattr(p, "qty", 0.0) or 0.0)
        price = float(getattr(p, "price", 0.0) or 0.0)
        rows.append({
            "відділ": str(getattr(p, "dept_id")),
            "артикул": str(getattr(p, "article")),
            "назва": str(getattr(p, "name") or ""),
            "кількість": qty,
            "ціна": price,
            "сума": qty * price,
            "активний": bool(getattr(p, "active", True)),
            "місяців без руху": float(getattr(p, "months_no_move", 0.0) or 0.0),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["відділ", "артикул", "назва", "кількість", "ціна", "сума", "активний", "місяців без руху"])
    return df


def _per_dept_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Зведення по відділах:
      • унікальних артикулів
      • загальна кількість (шт)
      • загальна сума
      • середня ціна (зважена по кількості, якщо можливо)
    """
    if df.empty:
        return pd.DataFrame(columns=["відділ", "унікальних артикулів", "шт (∑)", "сума (∑)", "середня ціна"])
    grp = df.groupby("відділ", dropna=False)

    def _weighted_avg_price(g: pd.DataFrame) -> float:
        qty = g.get("кількість")
        price = g.get("ціна")
        if qty is None or price is None or qty.fillna(0).sum() == 0:
            return float(price.fillna(0).mean()) if price is not None else 0.0
        return float((price.fillna(0) * qty.fillna(0)).sum() / qty.fillna(0).sum())

    res = pd.DataFrame({
        "унікальних артикулів": grp["артикул"].nunique(),
        "шт (∑)": grp["кількість"].sum(min_count=1),
        "сума (∑)": grp["сума"].sum(min_count=1)
    }).reset_index()

    # Середня ціна окремо
    avg_rows = []
    for dept, g in grp:
        avg_rows.append({"відділ": dept, "середня ціна": _weighted_avg_price(g)})
    avg_df = pd.DataFrame(avg_rows)

    out = pd.merge(res, avg_df, on="відділ", how="left")
    # Приведення форматів
    for c in ["шт (∑)", "сума (∑)", "середня ціна"]:
        if c in out.columns:
            out[c] = out[c].fillna(0.0).astype(float)
    return out.sort_values(by="відділ")


# ------------------------------ Основні API ----------------------------------

@dataclass
class ReportOptions:
    """Опції звітів."""
    dept_id: Optional[str] = None       # якщо None — всі відділи
    include_inactive: bool = False      # включати неактивні
    fmt: str = "xlsx"                   # "xlsx" | "ods" | "csv"
    kind: str = "unique"                # тип звіту для імені файлу
    sheet_name: str = "Звіт"            # ім'я аркуша для Excel/ODS


def build_products_df(opts: ReportOptions) -> pd.DataFrame:
    """
    Витягти дані з БД під звіт.
    """
    with get_session() as s:
        q = s.query(Product)
        if opts.dept_id:
            q = q.filter(Product.dept_id == str(opts.dept_id))
        if not opts.include_inactive:
            q = q.filter(Product.active == True)  # noqa: E712
        products = q.all()  # type: ignore
    return _df_unique_articles(products)


def build_summary_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Побудувати зведення по відділах на основі переліку товарів.
    """
    return _per_dept_summary(df)


def export_report(opts: ReportOptions) -> Path:
    """
    Побудувати звіт і записати його у файл у каталозі exports/.
    Повертає шлях до створеного файла.
    """
    df = build_products_df(opts)
    summary = build_summary_df(df)

    # Якщо конкретний відділ — робимо один аркуш
    # Якщо всі відділи — можемо записати два аркуші: "Перелік", "Зведення"
    path = _report_filename(opts.kind, opts.dept_id or None, opts.fmt)

    if opts.fmt.lower() in ("xlsx", "ods"):
        # Для простоти збережемо лише один аркуш. Якщо потрібно — можна зробити мульти-аркуші.
        # Тепер: якщо summary не пусте, пишемо саме summary. Інакше — повний перелік.
        df_to_write = summary if not summary.empty else df
        write_table(df_to_write, path, fmt=opts.fmt, sheet_name=opts.sheet_name, index=False)
    else:
        # CSV — тільки один набір даних
        df_to_write = summary if not summary.empty else df
        write_table(df_to_write, path, fmt="csv", index=False)

    # Ретеншн
    _cleanup_old_exports()
    return path


# ------------------------------ Хендлери TG ----------------------------------

def _kb_reports_main(dept: Optional[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    tag = dept or "all"
    kb.add(
        InlineKeyboardButton("🔢 Унікальні артикули", callback_data=f"rep:unique:{tag}"),
        InlineKeyboardButton("📦 Залишки і сума", callback_data=f"rep:stock:{tag}"),
    )
    kb.add(
        InlineKeyboardButton("🗂 Усі відділи (зведення)", callback_data="rep:unique:all"),
    )
    return kb


async def cmd_reports_start(message: types.Message):
    """
    Стартова точка меню звітів. Якщо твоє меню інше — підключиш ці хендлери туди.
    """
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("⛔ Немає прав для перегляду звітів.")
        return

    text = "📊 Оберіть звіт і відділ (або «усі відділи»)."
    await message.answer(text, reply_markup=_kb_reports_main(dept=None))


async def _run_and_send_report(message: types.Message, kind: str, dept_tag: str, fmt: str = "xlsx"):
    """
    Виконати генерацію звіту і відправити файл.
    """
    dept = None if dept_tag == "all" else dept_tag
    opts = ReportOptions(dept_id=dept, include_inactive=False, fmt=fmt, kind=kind,
                         sheet_name="Звіт")
    path = export_report(opts)
    await message.answer_document(types.InputFile(str(path)), caption=f"Звіт «{kind}», відділ: {dept or 'усі'}")


async def cb_report_menu(cb: types.CallbackQuery):
    """
    Обробка натискань на кнопки звітів.
    Формат callback_data: rep:<kind>:<dept|all>
    """
    try:
        _, kind, dept_tag = cb.data.split(":", 2)
    except Exception:
        await cb.answer("Невірний запит", show_alert=True)
        return

    await cb.answer()
    # За замовчуванням формуємо .xlsx
    await _run_and_send_report(cb.message, kind, dept_tag, fmt="xlsx")


# ------------------------------ Реєстрація ------------------------------------

def register(dp: Dispatcher) -> None:
    """
    Підключення хендлерів звітів.
    """
    dp.register_message_handler(cmd_reports_start, commands=["reports", "report"])
    dp.register_callback_query_handler(cb_report_menu, lambda c: c.data and c.data.startswith("rep:"))
