# -*- coding: utf-8 -*-
"""
Адмінська модерація фото товарів (aiogram 3.x).

Можливості:
- /photos_pending — показати перелік фото зі статусом pending (пачками).
- Відкрити фото з діями (approve / reject / order / set_main).
- Після approve/update порядку/призначення основного — інвалідувати кеш картки.

Залежності:
    database.session.get_session
    database.orm.products.ProductPhoto
    utils.card_cache.update_file_id / invalidate
"""

from __future__ import annotations

from typing import Optional, List

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)

from database.session import get_session  # type: ignore
from database.orm.products import ProductPhoto  # type: ignore
from utils.card_cache import update_file_id, invalidate  # type: ignore

router = Router(name="photo_admin")

# --------------------------- Допоміжні клавіатури -----------------------------

def _kb_pending_item(photo_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👁 Відкрити", callback_data=f"photo:open:{photo_id}")],
        ]
    )
    return kb


def _kb_photo_actions(dept_id: str, article: str, photo_id: int, current_order: int) -> InlineKeyboardMarkup:
    order_buttons = [
        InlineKeyboardButton(text="1️⃣", callback_data=f"photo:order:{photo_id}:1"),
        InlineKeyboardButton(text="2️⃣", callback_data=f"photo:order:{photo_id}:2"),
        InlineKeyboardButton(text="3️⃣", callback_data=f"photo:order:{photo_id}:3"),
    ]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"photo:approve:{photo_id}"),
             InlineKeyboardButton(text="🗑 Відхилити", callback_data=f"photo:reject:{photo_id}")],
            order_buttons,
            [InlineKeyboardButton(text="⭐ Зробити основним", callback_data=f"photo:set_main:{dept_id}:{article}:{photo_id}")],
        ]
    )
    return kb


# ------------------------------ Хелпери БД ------------------------------------

def _get_photo(photo_id: int) -> Optional[ProductPhoto]:
    with get_session() as s:
        return s.query(ProductPhoto).filter(ProductPhoto.id == int(photo_id)).one_or_none()


def _list_pending(limit: int = 20) -> List[ProductPhoto]:
    with get_session() as s:
        q = s.query(ProductPhoto).filter(ProductPhoto.status == "pending").order_by(ProductPhoto.id.desc())
        return q.limit(limit).all()  # type: ignore


def _set_status(photo_id: int, status: str) -> Optional[ProductPhoto]:
    with get_session() as s:
        row = s.query(ProductPhoto).filter(ProductPhoto.id == int(photo_id)).one_or_none()
        if not row:
            return None
        row.status = status
        s.commit()
        return row


def _set_order(photo_id: int, order_no: int) -> Optional[ProductPhoto]:
    order_no = max(1, min(3, int(order_no)))
    with get_session() as s:
        row = s.query(ProductPhoto).filter(ProductPhoto.id == int(photo_id)).one_or_none()
        if not row:
            return None
        row.order_no = order_no
        s.commit()
        return row


# ------------------------------ Команди/хендлери ------------------------------

@router.message(Command("photos_pending"))
async def photos_pending(message: Message):
    """
    Показати перші N фото на модерації (pending).
    """
    rows = _list_pending(limit=30)
    if not rows:
        await message.answer("Немає фото у статусі pending.")
        return

    for r in rows:
        caption = f"ID: {r.id}\nВідділ: {r.dept_id}\nАртикул: {r.article}\nСтатус: {r.status}\nПорядок: {r.order_no}"
        if r.file_id:
            await message.answer_photo(
                photo=r.file_id,
                caption=caption,
                reply_markup=_kb_pending_item(r.id),
            )
        else:
            await message.answer(
                text=caption,
                reply_markup=_kb_pending_item(r.id),
            )


@router.callback_query(F.data.startswith("photo:open:"))
async def cb_open_photo(cb: CallbackQuery):
    """
    Відкрити картку модерації одного фото.
    """
    try:
        _, _, id_str = cb.data.split(":", 2)
        pid = int(id_str)
    except Exception:
        await cb.answer("Помилковий ID", show_alert=True)
        return

    r = _get_photo(pid)
    if not r:
        await cb.answer("Фото не знайдено", show_alert=True)
        return

    caption = f"ID: {r.id}\nВідділ: {r.dept_id}\nАртикул: {r.article}\nСтатус: {r.status}\nПорядок: {r.order_no}"
    kb = _kb_photo_actions(str(r.dept_id), str(r.article), r.id, r.order_no)

    # Якщо у повідомленні вже було фото, редагуємо, інакше — створюємо нове з фото
    try:
        if cb.message.photo:
            await cb.message.edit_media(
                media=InputMediaPhoto(media=r.file_id, caption=caption),
                reply_markup=kb
            )
        else:
            await cb.message.answer_photo(photo=r.file_id, caption=caption, reply_markup=kb)
    except Exception:
        # Якщо file_id застарів — просто надсилаємо текст
        await cb.message.edit_text(text=caption, reply_markup=kb)

    await cb.answer()


@router.callback_query(F.data.startswith("photo:approve:"))
async def cb_approve_photo(cb: CallbackQuery):
    """
    Підтвердити фото: status -> approved, інвалідація кешу картки.
    """
    try:
        _, _, id_str = cb.data.split(":", 2)
        pid = int(id_str)
    except Exception:
        await cb.answer("Помилковий ID", show_alert=True)
        return

    row = _set_status(pid, "approved")
    if not row:
        await cb.answer("Фото не знайдено", show_alert=True)
        return

    # Інвалідуємо картку — щоб підхопила схвалене фото
    with get_session() as s:
        invalidate(s, str(row.dept_id), str(row.article))
        s.commit()

    await cb.answer("Схвалено ✅", show_alert=False)
    await cb.message.edit_reply_markup(reply_markup=_kb_photo_actions(str(row.dept_id), str(row.article), row.id, row.order_no))


@router.callback_query(F.data.startswith("photo:reject:"))
async def cb_reject_photo(cb: CallbackQuery):
    """
    Відхилити фото: status -> rejected.
    """
    try:
        _, _, id_str = cb.data.split(":", 2)
        pid = int(id_str)
    except Exception:
        await cb.answer("Помилковий ID", show_alert=True)
        return

    row = _set_status(pid, "rejected")
    if not row:
        await cb.answer("Фото не знайдено", show_alert=True)
        return

    await cb.answer("Відхилено 🗑", show_alert=False)
    await cb.message.edit_reply_markup(reply_markup=_kb_photo_actions(str(row.dept_id), str(row.article), row.id, row.order_no))


@router.callback_query(F.data.startswith("photo:order:"))
async def cb_set_order(cb: CallbackQuery):
    """
    Змінити порядок показу (1..3). Не змінює статус.
    """
    try:
        _, _, id_str, order_str = cb.data.split(":", 3)
        pid = int(id_str)
        order_no = int(order_str)
    except Exception:
        await cb.answer("Формат: order 1..3", show_alert=True)
        return

    row = _set_order(pid, order_no)
    if not row:
        await cb.answer("Фото не знайдено", show_alert=True)
        return

    await cb.answer(f"Порядок → {order_no}", show_alert=False)
    await cb.message.edit_reply_markup(reply_markup=_kb_photo_actions(str(row.dept_id), str(row.article), row.id, row.order_no))


@router.callback_query(F.data.startswith("photo:set_main:"))
async def cb_set_main(cb: CallbackQuery):
    """
    Позначити фото як основне для картки:
    - оновлюємо file_id у L2-кеші картки (та L1 автоматично через card_cache)
    - інвалідуємо картку, щоб наступне відкриття підтягнуло актуальний file_id
    """
    try:
        _, _, dept_id, article, id_str = cb.data.split(":", 4)
        pid = int(id_str)
    except Exception:
        await cb.answer("Помилкові дані", show_alert=True)
        return

    row = _get_photo(pid)
    if not row or str(row.dept_id) != str(dept_id) or str(row.article) != str(article):
        await cb.answer("Фото не знайдено", show_alert=True)
        return

    # Оновити file_id у кеші як основний
    with get_session() as s:
        update_file_id(s, str(dept_id), str(article), row.file_id)
        # Одразу інвалідуємо картку, щоб payload перегенерувався з актуальним file_id
        invalidate(s, str(dept_id), str(article))
        s.commit()

    await cb.answer("Призначено основним ⭐", show_alert=False)
