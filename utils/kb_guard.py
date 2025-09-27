# -*- coding: utf-8 -*-
"""
Захист від «глухих кутів» для aiogram 3.x.

Дає:
- safe_edit_or_send(bot, chat_id, text, *, message_id=None, parse_mode=None, reply_markup=None, disable_web_page_preview=None)
    Безпечно редагує повідомлення, а якщо не можна — шле нове. Гарантує клавіатуру.

- install_kb_audit(dp)
    Підключає middleware, який:
      * логуватиме повідомлення без клавіатури;
      * за потреби підставлятиме fallback-клавіатуру.

- @require_kb декоратор (NOP для v3, залишено для сумісності коду)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)


# ---------------------------- Fallback-клавіатура -----------------------------

def _fallback_kb() -> InlineKeyboardMarkup:
    """
    Мінімальна клавіатура, щоб юзер не застряг:
      - повернення до головного меню
      - відкриття мого списку
    Підлаштуй під свої callback-и, якщо вони інші.
    """
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 На головну", callback_data="main:back")],
        [InlineKeyboardButton(text="📦 Мій список", callback_data="main:my_list")],
    ])
    return kb


# ------------------------------- safe_edit_or_send ----------------------------

async def safe_edit_or_send(
    bot,
    chat_id: int | str,
    text: str,
    *,
    message_id: Optional[int] = None,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    disable_web_page_preview: Optional[bool] = None,
):
    """
    Надійно оновлює UI:
      1) Спроба edit_text (якщо передано message_id)
      2) Якщо падає — надсилає нове повідомлення send_message
    Завжди підставляє запасну клавіатуру, якщо хтось «забув» її додати.
    """
    if reply_markup is None:
        reply_markup = _fallback_kb()

    if message_id:
        try:
            return await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
        except Exception as e:
            # Часто рушиться, якщо повідомлення було з фото/документом або текст не змінився
            logger.debug("edit_message_text failed, falling back to send_message: %s", e)

    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


# ------------------------------ Middleware-аудит ------------------------------

@dataclass
class _KbAuditConfig:
    enforce_fallback: bool = True  # якщо True — підставляємо запасну клаву, якщо нема


class KbAuditMiddleware(BaseMiddleware):
    """
    Перехоплює вихідні відповіді хендлерів (Message/CallbackQuery), щоб:
      - зафіксувати випадки без клавіатури;
      - при бажанні підставити fallback-клаву.

    Примітка: у aiogram 3.x middleware працюють до/після обробки апдейту.
    Ми орієнтуємося на те, що більшість відповідей відправляються прямо з хендлерів.
    Тут ми тільки перехоплюємо CallbackQuery і, якщо треба, добиваємо кнопки.
    """
    def __init__(self, config: Optional[_KbAuditConfig] = None):
        super().__init__()
        self.config = config or _KbAuditConfig()

    async def __call__(self, handler, event, data):
        # До обробки
        result = await handler(event, data)
        # Після обробки: якщо це CallbackQuery без подальшої клавіатури — накинемо fallback.
        try:
            if isinstance(event, CallbackQuery):
                msg: Optional[Message] = event.message
                if msg and (msg.reply_markup is None or not getattr(msg.reply_markup, "inline_keyboard", None)):
                    logger.warning("KbAudit: повідомлення без клавіатури після callback '%s'", event.data)
                    if self.config.enforce_fallback:
                        try:
                            await event.message.edit_reply_markup(reply_markup=_fallback_kb())
                        except Exception:
                            # якщо редагувати не можна — просто відправимо нове
                            try:
                                await event.message.answer("Оновлено навігацію:", reply_markup=_fallback_kb())
                            except Exception:
                                pass
        except Exception as e:
            logger.debug("KbAudit post-hook error: %s", e)
        return result


# ---------------------------- Декоратор-сумісність ---------------------------

def require_kb(fn):
    """
    Заглушка-декоратор для сумісності з кодом під aiogram 2.x.
    У v3 нічого не робить.
    """
    async def wrapper(*args, **kwargs):
        return await fn(*args, **kwargs)
    return wrapper


# ------------------------------ Підключення ----------------------------------

def install_kb_audit(dp: Dispatcher, *, enforce_fallback: bool = True) -> None:
    """
    Підключення middleware до Dispatcher.
    """
    dp.update.middleware(KbAuditMiddleware(_KbAuditConfig(enforce_fallback=enforce_fallback)))
