# -*- coding: utf-8 -*-
"""
Хендлери для операції «📉 Відняти зібране» (адаптовані під aiogram 3.x).

Функціонал:
 - Приймає від адміна або менеджера текст зі списком позицій для списання.
 - Формати рядків:
     1) "артикул, кількість"               → напр. "12345678, 3"
     2) "назва..." де на початку є 8 цифр  → напр. "12345678 Носки чорні L, 2"
 - Кожен рядок окремо, порожні і коментарні (# ...) ігноруються.
 - Для кожної позиції:
     - Блокує товар у БД (SELECT ... FOR UPDATE SKIP LOCKED)
     - Зменшує qty на запитану кількість, але не нижче 0
     - Пише підсумковий звіт (скільки було, скільки знято, скільки стало)
 - Інвалідує кеш карток для зачеплених товарів (ProductCardCache).
 - В кінці надсилає короткий звіт по успішних і помилках.

Налаштування через .env:
 - SUBTRACT_ALLOWED_ROLES: "admin,manager" (за замовчуванням) — хто має право.
 - DEPT_DEFAULT: відділ за замовчуванням, якщо користувач його не вказує явно (опційно).

Залежності:
 - aiogram 3.x (Dispatcher імпортується з верхнього рівня `aiogram`)
 - SQLAlchemy ORM моделі: Product, ProductCardCache
 - фабрика сесій get_session()
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from aiogram import types, Dispatcher, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from dotenv import load_dotenv
from sqlalchemy import and_, text

# ORM та сесії
from database.orm.products import Product, ProductCardCache  # type: ignore
from database.session import get_session  # type: ignore

# За бажанням можемо використати наш guard, але файл не залежить від нього жорстко
try:
    from utils.kb_guard import safe_edit_or_send, require_kb  # type: ignore
except Exception:  # pragma: no cover
    async def safe_edit_or_send(bot, chat_id, text, *, message_id=None, parse_mode=None, reply_markup=None, disable_web_page_preview=None):
        return await bot.send_message(
            chat_id,
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )

    def require_kb(fn):  # noqa
        return fn

load_dotenv(override=True)

SUBTRACT_ALLOWED_ROLES = os.getenv("SUBTRACT_ALLOWED_ROLES", "admin,manager")
DEPT_DEFAULT = os.getenv("DEPT_DEFAULT", "").strip() or None

# Проста перевірка прав. У тебе може бути більш складна рольова модель.
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit())
MANAGER_IDS = set(int(x) for x in os.getenv("MANAGER_IDS", "").replace(" ", "").split(",") if x.strip().isdigit())


# ------------------------------ Парсинг вводу --------------------------------

ARTICLE_RE = re.compile(r"^\s*(\d{8})\b")  # 8 цифр на початку
LINE_SPLIT_RE = re.compile(r"[\r\n]+")


@dataclass
class SubtractItem:
    article: str
    qty: float
    dept_id: Optional[str] = None


def _extract_article(text: str) -> Optional[str]:
    """Витягти артикул з початку рядка."""
    if not isinstance(text, str):
        return None
    m = ARTICLE_RE.match(text)
    if not m:
        return None
    return m.group(1)


def _parse_line(line: str, default_dept: Optional[str]) -> Optional[SubtractItem]:
    """
    Парсити один рядок.
    Підтримувані формати:
        "12345678, 3"
        "12345678 назва, 2"
        "100:12345678, 5"   (якщо хочеш явно вказати відділ у рядку: dept:article, qty)
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return None

    # Варіант з явним відділом: 100:12345678, 5
    if ":" in s.split(",")[0]:
        head, *rest = s.split(",", 1)
        qty_str = rest[0] if rest else ""
        try:
            dept_part, art_part = head.split(":", 1)
            dept = dept_part.strip()
            art = _extract_article(art_part.strip())
            qty = float(qty_str.strip().replace(",", "."))
            if not art or qty <= 0:
                return None
            return SubtractItem(article=art, qty=qty, dept_id=dept)
        except Exception:
            return None

    # Звичайний варіант: "артикул, qty" або "артикул назва, qty"
    if "," in s:
        left, qty_str = s.split(",", 1)
        art = _extract_article(left)
        try:
            qty = float(qty_str.strip().replace(",", "."))
        except Exception:
            return None
        if not art or qty <= 0:
            return None
        return SubtractItem(article=art, qty=qty, dept_id=default_dept)

    # Без коми не приймаємо (щоб уникати неоднозначностей)
    return None


def parse_subtract_payload(text: str, default_dept: Optional[str]) -> List[SubtractItem]:
    """Розпарсити весь текст на позиції списання."""
    items: List[SubtractItem] = []
    for line in LINE_SPLIT_RE.split(text or ""):
        it = _parse_line(line, default_dept)
        if it:
            items.append(it)
    return items


# ------------------------------ Перевірка прав --------------------------------

def _is_allowed(user: types.User) -> bool:
    """Грубо: дозволити адмінам і менеджерам."""
    if user.id in ADMIN_IDS:
        return True
    if user.id in MANAGER_IDS and "manager" in SUBTRACT_ALLOWED_ROLES.lower():
        return True
    return False


# ------------------------------ База/транзакції -------------------------------

def _invalidate_card_cache(session, dept_id: str, article: str) -> None:
    """Видалити кеш картки для вказаного товару (L2)."""
    session.query(ProductCardCache).filter(
        ProductCardCache.dept_id == str(dept_id),
        ProductCardCache.article == str(article),
    ).delete(synchronize_session=False)


def _subtract_one(session, dept_id: str, article: str, qty: float) -> Tuple[float, float]:
    """
    Списати qty з продукту (але не нижче 0).
    Повертає (було, стало).
    Блокує рядок на час транзакції.
    """
    # Явний блок рядка. SQLAlchemy Core текстом, щоб не залежати від діалекту.
    lock_sql = text(
        """
        SELECT id FROM products
        WHERE dept_id = :dept_id AND article = :article
        FOR UPDATE SKIP LOCKED
    """
    )
    session.execute(lock_sql, {"dept_id": str(dept_id), "article": str(article)})

    # Отримати продукт
    prod = (
        session.query(Product)
        .filter(and_(Product.dept_id == str(dept_id), Product.article == str(article)))
        .one_or_none()
    )

    if not prod:
        raise ValueError("Товар не знайдено")

    before = float(prod.qty or 0.0)
    new_qty = before - float(qty)
    if new_qty < 0:
        new_qty = 0.0

    prod.qty = new_qty
    # Інвалідація кешу картки
    _invalidate_card_cache(session, dept_id, article)

    return before, new_qty


# ------------------------------ Хендлери TG -----------------------------------

def _kb_done() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("🏠 На головну", callback_data="go_home"))
    return kb


@require_kb
async def cmd_subtract_start(message: types.Message):
    """
    Старт діалогу списання. Пояснюємо формат, беремо відділ за замовчуванням.
    """
    if not _is_allowed(message.from_user):
        await message.reply("⛔ У вас немає прав для списання.")
        return

    dept_hint = (
        f"Відділ за замовчуванням: <b>{DEPT_DEFAULT}</b>"
        if DEPT_DEFAULT
        else "Відділ не задано (буде потрібен у рядках)."
    )
    text_msg = (
        "📉 <b>Відняти зібране</b>\n"
        f"{dept_hint}\n\n"
        "Надішліть повідомлення з позиціями, кожна з нового рядка. Приклади:\n"
        "<code>12345678, 3\n"
        "12345678 Шкарпетки чорні L, 2\n"
        "100:12345678, 5</code>\n\n"
        "Де 100 — код відділу (якщо потрібно вказати явно)."
    )
    await message.answer(text_msg, parse_mode="HTML", reply_markup=_kb_done())


@require_kb
async def handle_subtract_payload(message: types.Message):
    """
    Основний обробник: приймає текст, списує позиції, показує звіт.
    """
    if not _is_allowed(message.from_user):
        await message.reply("⛔ У вас немає прав для списання.")
        return

    items = parse_subtract_payload(message.text or "", DEPT_DEFAULT)
    if not items:
        await message.reply(
            "⚠️ Не знайшов жодної коректної позиції. Формат: <code>артикул, кількість</code> або <code>dept:артикул, кількість</code>.",
            parse_mode="HTML",
        )
        return

    # Агрегуємо однакові позиції для меншої кількості апдейтів
    agg: Dict[Tuple[str, str], float] = {}
    for it in items:
        dept = str(it.dept_id or "").strip()
        if not dept:
            await message.reply(
                "⚠️ Не вказано відділ і немає DEPT_DEFAULT. Додайте у рядку формат <code>dept:артикул, кількість</code> або налаштуйте DEPT_DEFAULT.",
                parse_mode="HTML",
            )
            return
        key = (dept, it.article)
        agg[key] = agg.get(key, 0.0) + float(it.qty)

    results: List[str] = []
    errors: List[str] = []

    from aiogram.utils.markdown import escape_md  # для безпечних вставок, якщо треба

    # Транзакційно списуємо
    try:
        with get_session() as s:
            for (dept, art), qty in agg.items():
                try:
                    before, after = _subtract_one(s, dept, art, qty)
                    results.append(f"• {dept}:{art}: {before:.2f} − {qty:.2f} → <b>{after:.2f}</b>")
                except ValueError:
                    errors.append(f"• {dept}:{art}: товар не знайдено")
                except Exception:
                    errors.append(f"• {dept}:{art}: помилка списання")
            s.commit()
    except Exception:
        # якщо щось критичне поза циклом
        errors.append(
            "Глобальна помилка транзакції. Частина позицій могла не застосуватись."
        )

    # Формуємо відповідь
    lines: List[str] = []
    lines.append("📉 <b>Результат списання</b>")
    if results:
        lines.append("\n".join(results))
    if errors:
        lines.append("")
        lines.append("⚠️ Помилки:")
        lines.append("\n".join(errors))

    # Якщо не було жодного успіху
    if not results and errors:
        await message.answer(
            "\n".join(lines), parse_mode="HTML", reply_markup=_kb_done()
        )
        return

    # Підсумок
    ok_cnt = len(results)
    err_cnt = len(errors)
    lines.append("")
    lines.append(f"Підсумок: успішно — <b>{ok_cnt}</b>, помилок — <b>{err_cnt}</b>.")

    await message.answer(
        "\n".join(lines), parse_mode="HTML", reply_markup=_kb_done()
    )


# ------------------------------ Реєстрація ------------------------------------

def register(dp: Dispatcher) -> None:
    """
    Реєстрація хендлерів списання.
    Пропонується мати окрему команду/кнопку в адмінці, яка веде сюди.
    """
    # Стартова команда
    dp.message.register(cmd_subtract_start, Command("subtract", "minus"))
    # Реєстрація основного обробника тексту з використанням regexp через magic-filter
    dp.message.register(
        handle_subtract_payload,
        F.text.regexp(r"^\s*(\d{8}|(\d{1,4}:\d{8}))\b.*?,\s*[-+]?\d+([.,]\d+)?\s*$"),
    )
