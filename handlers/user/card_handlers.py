# -*- coding: utf-8 -*-
"""
Хендлери для роботи з картками товарів.
Використовуємо кеш карток (L1/L2) і безпечне редагування повідомлень.
"""

from __future__ import annotations

from aiogram import types
from aiogram.dispatcher import Dispatcher

from database.session import get_session  # type: ignore
from utils.card_cache import get_or_render_card
from utils.renderers import render_product_card
from utils.kb_guard import safe_edit_or_send, require_kb
from keyboards.inline import get_cached_product_kb


def _render_text(card: dict) -> str:
    """
    Побудувати текст картки для Telegram.
    """
    lines = []
    lines.append(f"<b>{card.get('title') or ''}</b>")
    if card.get("subtitle"):
        lines.append(card["subtitle"])
    lines.append(f"📦 Доступно: <b>{card.get('available', 0):.2f}</b>")
    lines.append(f"💵 Ціна: <b>{card.get('price', 0):.2f}</b>")
    if card.get("note"):
        lines.append(f"ℹ️ {card['note']}")
    return "\n".join(lines)


@require_kb
async def open_product(cb: types.CallbackQuery):
    """
    Відкрити картку товару з кешу.
    Формат callback_data: open:<dept_id>:<article>
    """
    try:
        _, dept_id, article = cb.data.split(":", 2)
    except Exception:
        await cb.answer("Помилка запиту", show_alert=True)
        return

    with get_session() as s:
        payload = get_or_render_card(s, dept_id, article, render_product_card)

    text = _render_text(payload)
    kb = get_cached_product_kb(payload["dept_id"], payload["article"], payload.get("can_add", False))

    file_id = payload.get("file_id")
    if file_id:
        try:
            await cb.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            try:
                await cb.message.bot.send_photo(
                    cb.message.chat.id,
                    photo=file_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            except Exception:
                await safe_edit_or_send(
                    cb.message.bot,
                    cb.message.chat.id,
                    text,
                    message_id=cb.message.message_id,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
    else:
        await safe_edit_or_send(
            cb.message.bot,
            cb.message.chat.id,
            text,
            message_id=cb.message.message_id,
            parse_mode="HTML",
            reply_markup=kb,
        )

    await cb.answer()


def register(dp: Dispatcher) -> None:
    """
    Реєстрація хендлерів у Dispatcher.
    """
    dp.register_callback_query_handler(open_product, lambda c: c.data and c.data.startswith("open:"))
