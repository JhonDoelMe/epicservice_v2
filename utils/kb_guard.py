# -*- coding: utf-8 -*-
"""
Захист від «глухих кутів» для aiogram 3.x.

Цей модуль забезпечує невидиму навігацію для користувача, якщо хендлер
забув додати клавіатуру до відповіді. Він також надає зручні утиліти
для безпечної модифікації повідомлень (edit_vs_send) і декоратор
`require_kb` для сумісності з кодом, написаним під aiogram 2.x.

Можливості
----------

* ``safe_edit_or_send`` — безпечно оновлює текст повідомлення, а якщо
  редагування не можливе (наприклад, бот відповідав на фото або текст не
  змінюється), надсилає нове повідомлення. Завжди гарантує наявність
  fallback‑клавіатури.
* ``install_kb_audit`` — підключає middleware до ``Dispatcher`` для
  автоматичного моніторингу випадків, коли після callback відсутня
  клавіатура. За необхідності додає запасну.
* ``require_kb`` — заглушка‑декоратор для сумісності. У версії 3.x
  ``aiogram`` не підтримує примусову перевірку клавіатур, тому функція
  повертає обгорнутий виклик без змін.

Підлаштовуйте функцію ``_fallback_kb()`` під ваші callback‑дані, щоб
кнопки «🏠 На головну» та «📦 Мій список» вели у потрібні місця.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


# ---------------------------- Fallback-клавіатура -----------------------------

def _fallback_kb() -> InlineKeyboardMarkup:
    """
    Мінімальна клавіатура, щоб користувач не застряг без варіантів.

    Кнопки слід адаптувати під ваші callback_data. За замовчуванням
    пропонується кнопка повернення на головний екран і відкриття
    персонального списку користувача.
    """
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 На головну", callback_data="main:back")],
            [InlineKeyboardButton(text="📦 Мій список", callback_data="main:my_list")],
        ]
    )
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
) -> Message:
    """
    Надійно оновлює UI:

    1. Якщо ``message_id`` передано — спробує відредагувати текст
       повідомлення ``edit_message_text``.
    2. Якщо редагування неможливе (наприклад, повідомлення містить фото
       або документ, або текст не змінився), надсилає нове повідомлення
       ``send_message``.

    Усі відповіді завжди мають клавіатуру: якщо ``reply_markup`` не
    передано, використовується ``_fallback_kb()``. Це запобігає ситуації,
    коли користувач не має кнопок для навігації.
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
            # Редагування часто падає для повідомлень з медіа або якщо текст не змінився
            logger.debug("safe_edit_or_send: edit_message_text failed, falling back to send_message: %s", e)

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
    """Параметри конфігурації для аудиту клавіатур."""
    enforce_fallback: bool = True  # якщо True — додається fallback, коли немає власної клавіатури


class KbAuditMiddleware(BaseMiddleware):
    """
    Middleware для перехоплення CallbackQuery та гарантування наявності клавіатури.

    Після виконання хендлера перевіряє, чи повідомлення, пов'язане з
    callback, має клавіатуру. Якщо ні, логуватиме попередження і, за
    конфігурацією, додаватиме fallback‑клавіатуру (редагуючи markup або
    надсилаючи нове повідомлення).
    """

    def __init__(self, config: Optional[_KbAuditConfig] = None):
        super().__init__()
        self.config = config or _KbAuditConfig()

    async def __call__(self, handler, event, data):
        # Викликаємо хендлер спочатку
        result = await handler(event, data)
        # Після обробки: якщо це CallbackQuery — перевіряємо наявність клавіатури
        try:
            if isinstance(event, CallbackQuery):
                msg: Optional[Message] = event.message
                if msg and (msg.reply_markup is None or not getattr(msg.reply_markup, "inline_keyboard", None)):
                    logger.warning(
                        "KbAudit: повідомлення без клавіатури після callback '%s'", event.data
                    )
                    if self.config.enforce_fallback:
                        try:
                            await event.message.edit_reply_markup(reply_markup=_fallback_kb())
                        except Exception:
                            # Якщо редагувати не можна, намагаємося відповісти новим повідомленням
                            try:
                                await event.message.answer(
                                    "Оновлено навігацію:", reply_markup=_fallback_kb()
                                )
                            except Exception:
                                # У крайніх випадках ігноруємо
                                pass
        except Exception as e:
            logger.debug("KbAudit post-hook error: %s", e)
        return result


# ---------------------------- Декоратор-сумісність ---------------------------

def require_kb(fn):
    """
    Заглушка‑декоратор для сумісності з aiogram 2.x.

    У версії 3.x aiogram змінилося API для клавіатур. Деякий код ще може
    викликати ``@require_kb`` для контролю наявності клавіатури. Щоб не
    ламати підписів функцій, ми повертаємо обгортку, яка викликає
    оригінальну функцію без додаткових перевірок.
    """
    async def wrapper(*args, **kwargs):
        return await fn(*args, **kwargs)
    return wrapper


# ------------------------------ Підключення ----------------------------------

def install_kb_audit(dp: Dispatcher, *, enforce_fallback: bool = True) -> None:
    """
    Підключити KbAuditMiddleware до Dispatcher.

    Виклик ``install_kb_audit(dp)`` у твоєму ``bot.py`` реєструє middleware,
    який стежить за callback‑ами та додає fallback‑клавіатуру там, де це
    необхідно.

    Parameters
    ----------
    dp : Dispatcher
        Диспетчер aiogram 3.x, до якого додається middleware.
    enforce_fallback : bool, optional
        Якщо True, middleware примусово додає fallback‑клавіатуру при її
        відсутності. Якщо False, лише логуватиме попередження.
    """
    dp.update.middleware(KbAuditMiddleware(_KbAuditConfig(enforce_fallback=enforce_fallback)))