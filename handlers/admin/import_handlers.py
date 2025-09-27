#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Адмінські хендлери імпорту даних (Excel/ODS/CSV) із dry‑run та підтвердженням.

Ця версія доповнена підтримкою кнопки «📥 Імпорт товарів з Excel» у адмін‑панелі.
Коли адміністратор натискає цю кнопку, бот показує інструкції щодо імпорту та
пропонує надіслати файл. Подальша логіка імпорту (dry‑run та підтвердження)
реалізована нижче.

Функціонал:
 - Прийом файлу від адміністратора (xlsx/xlsm/ods/csv)
 - Нормалізація таблиці (utils/import_normalizer.py)
 - Dry‑run: підрахунок доданих/оновлених/деактивованих, унікальних артикулів,
   сум по відділам
 - Запобіжник: якщо у файлі не виявлено ЖОДНОГО артикула — імпорт
   скасовується, БД не чіпається
 - Поріг «масової деактивації» (відносний) з .env; якщо перевищено —
   деактивацію не виконуємо (тільки додаємо/оновлюємо)
 - Підтвердження імпорту через inline‑клавіатуру
 - Звіт після застосування

Додано: обробник для admin:import_products, який викликається при натисканні
кнопки «Імпорт товарів з Excel» у адмін‑панелі. Він відправляє інструкцію й
пропонує повернутися назад до адмін‑панелі.

"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from aiogram import Bot, types, Dispatcher, F  # Dispatcher imported from aiogram root in v3
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv

# ------------------------------ КОНФІГ ---------------------------------------

load_dotenv(override=True)
logger = logging.getLogger(__name__)

IMPORTS_DIR = Path(os.getenv("IMPORTS_DIR", "imports")).resolve()
PLANS_DIR = IMPORTS_DIR / "_plans"
PLANS_DIR.mkdir(parents=True, exist_ok=True)

# Поріг масової деактивації (частка від 0 до 1). Якщо кандидатів на деактивацію більше — деактивацію відрубимо.
MAX_DEACTIVATE_SHARE = float(os.getenv("IMPORT_MAX_DEACTIVATE_SHARE", "0.5"))

# Чи деактивувати відсутні в імпорті позиції у відповідних відділах (за замовчуванням так)
DEACTIVATE_MISSING = os.getenv("IMPORT_DEACTIVATE_MISSING", "1") in ("1", "true", "True", "yes", "YES")

# Розширення, які дозволено
ALLOWED_EXT = {".xlsx", ".xlsm", ".ods", ".csv"}

# Кому дозволено імпорт (список ID через кому). Якщо порожньо — дозволено лише ADMIN_IDS.
ADMIN_IDS_ENV = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = set(int(x) for x in ADMIN_IDS_ENV.replace(" ", "").split(",") if x.strip().isdigit())


# ---------------------- ІМПОРТИ УТИЛІТ НОРМАЛІЗАЦІЇ -------------------------

from utils.io_spreadsheet import read_any_spreadsheet
from utils.import_normalizer import normalize_import_table, NoArticlesError

# ----------------------------- ORM І СЕСІЇ -----------------------------------
# Підлаштуй під свій проєкт:

try:
    # Варіант 1: у тебе є такі модулі
    from database.orm.products import Product  # type: ignore
    from database.session import get_session   # type: ignore
except Exception:
    # Варіант 2: запасні заглушки для пояснень (виняток при використанні)
    class Product:  # type: ignore
        pass

    def get_session():  # type: ignore
        raise RuntimeError("Підключи get_session() і Product з твоєї ORM.")


# ----------------------------- ДАТАКЛАСИ ПЛАНУ -------------------------------

@dataclass
class PlanItem:
    article: str
    dept_id: str
    name: Optional[str] = None
    qty: Optional[float] = None
    price: Optional[float] = None
    months_no_move: Optional[float] = None


@dataclass
class ImportPlan:
    """
    План застосування імпорту, що зберігається на диску до підтвердження.
    """
    token: str
    # Списки операцій
    to_insert: List[PlanItem] = field(default_factory=list)
    to_update: List[PlanItem] = field(default_factory=list)
    # По відділах, яких торкається імпорт
    involved_depts: List[str] = field(default_factory=list)
    # Кандидати на деактивацію (артикул+відділ існували в БД, але відсутні у файлі)
    to_deactivate: List[Tuple[str, str]] = field(default_factory=list)  # (article, dept_id)
    # Прапорець: зрізати деактивацію, якщо перевищено поріг
    deactivate_allowed: bool = True
    # Корисна статистика
    stats: Dict[str, float] = field(default_factory=dict)
    # Людяний підсумковий звіт для відображення
    human_report: str = ""

    def to_json(self) -> dict:
        return {
            "token": self.token,
            "to_insert": [asdict(x) for x in self.to_insert],
            "to_update": [asdict(x) for x in self.to_update],
            "involved_depts": self.involved_depts,
            "to_deactivate": list(self.to_deactivate),
            "deactivate_allowed": self.deactivate_allowed,
            "stats": self.stats,
            "human_report": self.human_report,
        }

    @staticmethod
    def from_json(d: dict) -> "ImportPlan":
        plan = ImportPlan(
            token=d["token"],
            to_insert=[PlanItem(**x) for x in d.get("to_insert", [])],
            to_update=[PlanItem(**x) for x in d.get("to_update", [])],
            involved_depts=d.get("involved_depts", []),
            to_deactivate=[tuple(x) for x in d.get("to_deactivate", [])],
            deactivate_allowed=d.get("deactivate_allowed", True),
            stats=d.get("stats", {}),
            human_report=d.get("human_report", ""),
        )
        return plan


# ------------------------------ ДОПОМОЖНІ ------------------------------------

def is_admin(user: types.User) -> bool:
    """Перевірити, чи має користувач право на імпорт."""
    if ADMIN_IDS and user.id in ADMIN_IDS:
        return True
    # Якщо ADMIN_IDS порожній, імовірно у тебе є інший глобальний механізм прав.
    # За замовчуванням — дозволено лише тим, хто у ADMIN_IDS.
    return bool(ADMIN_IDS)


def _short_token() -> str:
    """Короткий токен для callback_data (64 байти обмеження)."""
    return hex(int(time.time() * 1000))[2:][-8:]


def _save_plan(plan: ImportPlan) -> Path:
    p = PLANS_DIR / f"{plan.token}.json"
    with p.open("w", encoding="utf-8") as f:
        json.dump(plan.to_json(), f, ensure_ascii=False, indent=2)
    return p


def _load_plan(token: str) -> ImportPlan:
    p = PLANS_DIR / f"{token}.json"
    if not p.exists():
        raise FileNotFoundError("План імпорту не знайдено або він протермінований.")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return ImportPlan.from_json(data)


def _humanize_report(stats: Dict[str, float],
                      ins: int, upd: int, deact: int, deact_allowed: bool,
                      per_dept: Dict[str, Dict[str, float]]) -> str:
    lines = []
    lines.append("📥 <b>Dry-run імпорту</b>")
    lines.append("")
    lines.append(f"• Унікальних артикулів у файлі: <b>{int(stats.get('articles_unique', 0))}</b>")
    lines.append(f"• Рядків у файлі: <b>{int(stats.get('rows_total', 0))}</b>")
    lines.append("")
    lines.append(f"✅ Додати: <b>{ins}</b>")
    lines.append(f"🔁 Оновити: <b>{upd}</b>")
    if DEACTIVATE_MISSING:
        deact_line = f"🗂 Деактивувати (не у файлі): <b>{deact}</b>"
        if not deact_allowed and deact > 0:
            deact_line += "  <i>(порог перевищено, деактивацію вимкнено)</i>"
        lines.append(deact_line)
    else:
        lines.append("🗂 Деактивувати: <i>вимкнено налаштуванням</i>")
    lines.append("")
    if per_dept:
        lines.append("<b>Суми по відділах:</b>")
        for dept, d in sorted(per_dept.items(), key=lambda x: str(x[0])):
            s = f"  • Відділ {dept}: унікальних артикулів — {int(d.get('unique', 0))}, сума — {d.get('sum', 0):.2f}"
            lines.append(s)
    return "\n".join(lines)


def _kb_confirm(token: str) -> InlineKeyboardMarkup:
    """Створює клавіатуру підтвердження для імпорту.

    У aiogram 3.x необхідно передавати ``inline_keyboard`` під час
    ініціалізації ``InlineKeyboardMarkup``, інакше виникає валідаційна помилка.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Застосувати імпорт",
                    callback_data=f"imp_apply:{token}"
                ),
                InlineKeyboardButton(
                    text="❌ Скасувати",
                    callback_data=f"imp_cancel:{token}"
                ),
            ]
        ]
    )


# ------------------------------ ОСНОВНА ЛОГІКА --------------------------------

def _prepare_import_plan(df: pd.DataFrame) -> ImportPlan:
    """
    Побудувати план імпорту: що додати, що оновити, що деактивувати.
    Деактивація рахується тільки по тих відділах, які присутні у файлі.
    """
    token = _short_token()
    plan = ImportPlan(token=token)

    # Які відділи в імпорті
    if "відділ" in df.columns:
        involved_depts = sorted(set(str(x) for x in df["відділ"].dropna().astype(str).tolist()))
    else:
        involved_depts = ["unknown"]
    plan.involved_depts = involved_depts

    # Підготуємо індекс для швидких зіставлень
    df["__key"] = df.apply(lambda r: f"{str(r.get('відділ', 'unknown'))}::{str(r['артикул'])}", axis=1)

    # Агрегати по відділах
    per_dept: Dict[str, Dict[str, float]] = {}
    for dept in involved_depts:
        sub = df[df.get("відділ", "unknown").astype(str) == dept]
        unique = int(sub["артикул"].dropna().astype(str).nunique()) if "артикул" in sub.columns else 0
        total_sum = float(sub.get("сума", pd.Series(dtype=float)).fillna(0).astype(float).sum()) if "сума" in sub.columns else 0.0
        per_dept[dept] = {"unique": float(unique), "sum": float(total_sum)}

    # Зчитаємо стан БД
    with get_session() as s:
        # Усе, що у відділах з імпорту
        db_items = s.query(Product).filter(Product.dept_id.in_(involved_depts)).all()  # type: ignore
        db_map: Dict[str, Product] = {f"{str(p.dept_id)}::{str(p.article)}": p for p in db_items}

    # Визначаємо вставки/оновлення
    to_insert: List[PlanItem] = []
    to_update: List[PlanItem] = []

    def _row2item(row: pd.Series) -> PlanItem:
        return PlanItem(
            article=str(row.get("артикул")),
            dept_id=str(row.get("відділ", "unknown")),
            name=str(row.get("назва")) if not pd.isna(row.get("назва")) else None,
            qty=float(row.get("кількість")) if "кількість" in row and not pd.isna(row.get("кількість")) else None,
            price=float(row.get("ціна")) if "ціна" in row and not pd.isna(row.get("ціна")) else None,
            months_no_move=float(row.get("місяців без руху")) if "місяців без руху" in row and not pd.isna(row.get("місяців без руху")) else None,
        )

    for _, row in df.iterrows():
        key = row["__key"]
        if key in db_map:
            to_update.append(_row2item(row))
        else:
            to_insert.append(_row2item(row))

    # Кандидати на деактивацію: те, що є в БД у цих відділах, але нема у файлі
    imported_keys = set(df["__key"].tolist())
    to_deactivate: List[Tuple[str, str]] = []
    for key, item in db_map.items():
        if key not in imported_keys and DEACTIVATE_MISSING:
            to_deactivate.append((str(item.article), str(item.dept_id)))

    # Поріг масової деактивації
    deactivate_allowed = True
    total_db_involved = len(db_map) or 1  # щоб уникнути ділення на нуль
    share = len(to_deactivate) / float(total_db_involved)
    if share > MAX_DEACTIVATE_SHARE:
        deactivate_allowed = False

    # Пакуємо
    plan.to_insert = to_insert
    plan.to_update = to_update
    plan.to_deactivate = to_deactivate
    plan.deactivate_allowed = deactivate_allowed
    plan.stats = {"rows_total": float(len(df)), "articles_unique": float(df["артикул"].nunique())}
    plan.human_report = _humanize_report(plan.stats, len(to_insert), len(to_update), len(to_deactivate), deactivate_allowed, per_dept)

    return plan


# ----------------------------- ХЕНДЛЕРИ TG -----------------------------------

async def _handle_import_file(message: types.Message, bot: Bot) -> None:
    """
    Приймає документ від адміна, зберігає у ./imports, робить dry-run, показує звіт і кнопки підтвердження.
    """
    if not message.document:
        return

    if not is_admin(message.from_user):
        await message.reply("⛔ У вас немає прав на імпорт.")
        return

    file_name = message.document.file_name or "upload"
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXT:
        await message.reply("Формат не підтримується. Дозволено: .xlsx, .xlsm, .ods, .csv")
        return

    # Завантажити файл у imports/
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%d.%m.%Y_%H.%M")
    saved_path = IMPORTS_DIR / f"import_{ts}{ext}"

    file = await bot.get_file(message.document.file_id)
    await bot.download_file(file.file_path, destination=saved_path)

    # Прочитати і нормалізувати
    try:
        # read_any_spreadsheet expects a string path; convert Path to str
        raw_df = read_any_spreadsheet(str(saved_path))
        norm = normalize_import_table(raw_df).require_any_articles()
    except NoArticlesError:
        await message.answer("⚠️ Імпорт скасовано: не знайдено жодного артикула у файлі.\n"
                             "Базу не змінено.")
        logger.warning("Import canceled: no articles.")
        return
    except Exception as e:
        logger.exception("Помилка читання/нормалізації імпорту: %s", e)
        await message.answer("❌ Помилка під час читання файлу або нормалізації.\n"
                             "Перевірте заголовки колонок і формат.")
        return

    # Побудувати план dry-run
    plan = _prepare_import_plan(norm.df)

    # Якщо немає жодного запису на додавання/оновлення/деактивацію — повідомити
    if not plan.to_insert and not plan.to_update and not (DEACTIVATE_MISSING and plan.to_deactivate):
        await message.answer("ℹ️ У файлі немає змін для застосування. Базу не змінюю.")
        return

    # Зберегти план
    _save_plan(plan)

    # Показати звіт і кнопки
    await message.answer(
        plan.human_report,
        parse_mode="HTML",
        reply_markup=_kb_confirm(plan.token)
    )


async def _cb_apply_import(cb: types.CallbackQuery) -> None:
    """
    Застосувати раніше підготовлений план імпорту.
    """
    if not is_admin(cb.from_user):
        await cb.answer("Немає прав.", show_alert=True)
        return

    token = cb.data.split(":", 1)[1]
    try:
        plan = _load_plan(token)
    except Exception:
        await cb.answer("План імпорту не знайдено або застарів.", show_alert=True)
        return

    # Застосування плану
    try:
        ins_cnt = upd_cnt = deact_cnt = 0
        with get_session() as s:
            # Індекси існуючих
            existing: Dict[Tuple[str, str], Product] = {}
            q = s.query(Product).filter(Product.dept_id.in_(plan.involved_depts))
            for p in q.all():  # type: ignore
                existing[(str(p.article), str(p.dept_id))] = p

            # INSERT
            for it in plan.to_insert:
                key = (it.article, it.dept_id)
                if key in existing:
                    # параноя: якщо раптом з'явився за час dry-run → в оновлення
                    p = existing[key]
                    if it.name is not None:
                        p.name = it.name
                    if it.qty is not None:
                        p.qty = it.qty
                    if it.price is not None:
                        p.price = it.price
                    if it.months_no_move is not None:
                        p.months_no_move = it.months_no_move
                    p.active = True  # на всяк випадок
                    upd_cnt += 1
                else:
                    p = Product()  # type: ignore
                    p.article = it.article
                    p.dept_id = it.dept_id
                    p.name = it.name or ""
                    p.qty = it.qty or 0
                    p.price = it.price or 0
                    p.months_no_move = it.months_no_move or 0
                    p.active = True
                    s.add(p)
                    ins_cnt += 1

            # UPDATE
            for it in plan.to_update:
                key = (it.article, it.dept_id)
                p = existing.get(key)
                if not p:
                    # хтось видалив між dry-run і apply — перетворимо на insert
                    p = Product()  # type: ignore
                    p.article = it.article
                    p.dept_id = it.dept_id
                    p.active = True
                    s.add(p)
                    ins_cnt += 1
                # оновлення полів
                if it.name is not None:
                    p.name = it.name
                if it.qty is not None:
                    p.qty = it.qty
                if it.price is not None:
                    p.price = it.price
                if it.months_no_move is not None:
                    p.months_no_move = it.months_no_move
                p.active = True

            # DEACTIVATE
            if DEACTIVATE_MISSING and plan.deactivate_allowed and plan.to_deactivate:
                for art, dept in plan.to_deactivate:
                    p = existing.get((art, dept))
                    if p and getattr(p, "active", True):
                        p.active = False
                        deact_cnt += 1

            s.commit()

        msg = [
            "✅ <b>Імпорт застосовано</b>",
            f"• Додано: <b>{ins_cnt}</b>",
            f"• Оновлено: <b>{upd_cnt}</b>",
        ]
        if DEACTIVATE_MISSING:
            if plan.deactivate_allowed:
                msg.append(f"• Деактивовано: <b>{deact_cnt}</b>")
            else:
                msg.append("• Деактивовано: <i>пропущено (перевищено поріг масової деактивації)</i>")
        await cb.message.edit_text("\n".join(msg), parse_mode="HTML")
        await cb.answer("Готово")
    except Exception as e:
        logger.exception("Застосування імпорту впало: %s", e)
        await cb.answer("Помилка застосування імпорту", show_alert=True)


async def _cb_cancel_import(cb: types.CallbackQuery) -> None:
    token = cb.data.split(":", 1)[1]
    try:
        p = PLANS_DIR / f"{token}.json"
        if p.exists():
            p.unlink()
    except Exception:
        pass
    try:
        await cb.message.edit_text("❎ Імпорт скасовано.")
    except Exception:
        pass
    await cb.answer("Скасовано")


# ------------------------ НОВИЙ ХЕНДЛЕР КНОПКИ ІМПОРТУ -----------------------

async def cb_import_products_start(cb: types.CallbackQuery) -> None:
    """
    Handler for the admin menu button 'Import products from Excel'.

    When the administrator presses the «📥 Імпорт товарів з Excel» button, this
    handler sends a message with instructions on how to upload a spreadsheet
    and provides a back button to return to the admin panel.
    """
    if not is_admin(cb.from_user):
        await cb.answer("Немає прав.", show_alert=True)
        return

    # Inline keyboard with a 'back to admin panel' button
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main")]
        ]
    )

    await cb.message.edit_text(
        "📂 Будь ласка, надішліть файл Excel/ODS/CSV для імпорту товарів.\n"
        "Файл повинен містити колонки: артикул, відділ, назва, кількість, ціна, місяців без руху.\n\n"
        "Після завантаження бот покаже dry-run і попередній звіт для підтвердження.",
        reply_markup=kb
    )
    await cb.answer()


# ----------------------------- РЕЄСТРАЦІЯ ------------------------------------

def register(dp: Dispatcher) -> None:
    """
    Підключення хендлерів імпорту.
    - Документи від адмінів із розширенням .xlsx/.xlsm/.ods/.csv — тригер dry-run
    - Callback кнопки підтвердження/скасування
    - Callback кнопки запуску імпорту з адмін‑панелі
    """
    # Прийом документів (будь-який чат), але фільтруємо по розширенню
    async def on_document(message: types.Message):
        """
        Handle incoming documents. If the document has an allowed extension, trigger a dry-run import.
        """
        doc: types.Document = message.document
        name = (doc.file_name or "").lower()
        if not any(name.endswith(ext) for ext in ALLOWED_EXT):
            return  # not our format
        
        # Використовуємо message.bot для коректного доступу до Bot
        await _handle_import_file(message, message.bot) 
        
    # Використання v3 API: dp.message.register з F-фільтром ContentType
    dp.message.register(on_document, F.content_type == types.ContentType.DOCUMENT)

    # Підтвердження/скасування імпорту
    dp.callback_query.register(
        _cb_apply_import,
        F.data.startswith("imp_apply:")
    )
    dp.callback_query.register(
        _cb_cancel_import,
        F.data.startswith("imp_cancel:")
    )

    # Обробник кнопки «Імпорт товарів з Excel» у адмін-панелі
    dp.callback_query.register(
        cb_import_products_start,
        F.data == "admin:import_products"
    )