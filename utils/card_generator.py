# epicservice/utils/card_generator.py

"""
Генератор карток для відображення інформації про товар у Telegram.

Цей модуль формує текст картки та клавіатуру дій для товарів. Він
використовує українську модель товару (``database.models.Product``) та
розраховує доступні кількості з урахуванням резервів. Також у цьому
варіанті покращено форматування місяців без руху: цілі числа відображаються
без дробової частини (наприклад, ``5`` замість ``5.0``).
"""

import logging
from typing import Union

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from database.models import Product
from database.orm import (
    orm_get_temp_list_item_quantity,
    orm_get_total_temp_reservation_for_product,
)
from keyboards.inline import get_product_actions_kb
from lexicon.lexicon import LEXICON
from utils.markdown_corrector import escape_markdown

logger = logging.getLogger(__name__)


def format_quantity(quantity_str: str) -> Union[int, float, str]:
    """
    Форматує рядок з кількістю у число (int або float).
    Повертає int, якщо число ціле, інакше float.
    Якщо конвертація неможлива, повертає оригінальний рядок.
    """
    try:
        quantity_float = float(str(quantity_str).replace(',', '.'))
        return int(quantity_float) if quantity_float.is_integer() else quantity_float
    except (ValueError, TypeError):
        return quantity_str


async def send_or_edit_product_card(
    bot: Bot,
    chat_id: int,
    user_id: int,
    product: Product,
    message_id: int = None,
    search_query: str | None = None,
) -> Message | None:
    """
    Формує та надсилає (або редагує) картку товару.
    Тепер повертає об'єкт надісланого або відредагованого повідомлення.
    """
    try:
        in_user_temp_list_qty = await orm_get_temp_list_item_quantity(user_id, product.id)
        total_temp_reserved = await orm_get_total_temp_reservation_for_product(product.id)

        try:
            # Загальна кількість товару на складі
            stock_quantity = float(str(product.кількість).replace(',', '.'))
            # Постійно зарезервована кількість (значення з БД)
            permanently_reserved = product.відкладено or 0
            # Доступно для будь‑кого = на складі – відкладено – тимчасові резерви інших користувачів
            available_for_anyone_qty = stock_quantity - permanently_reserved - total_temp_reserved

            # Форматовані значення для виводу
            display_available_qty = format_quantity(available_for_anyone_qty)
            display_user_reserved_qty = format_quantity(in_user_temp_list_qty)

            # Кількість для кнопок (ціле число, не менше нуля)
            int_available_for_button = max(0, int(available_for_anyone_qty))

            price = product.ціна or 0.0

            current_stock_sum = available_for_anyone_qty * price
            reserved_sum = in_user_temp_list_qty * price

            display_stock_sum = f"{current_stock_sum:.2f}" if product.сума_залишку is not None else "---"
            # Місяці без руху: відображаємо без зайвої дробової частини
            if product.місяці_без_руху is not None:
                display_months = format_quantity(product.місяці_без_руху)
            else:
                display_months = "---"

        except (ValueError, TypeError):
            # Якщо конвертація кількості не вдалася, показуємо оригінальне значення
            display_available_qty = product.кількість
            int_available_for_button = 0
            display_user_reserved_qty = in_user_temp_list_qty
            display_stock_sum = "---"
            reserved_sum = "---"
            display_months = "---"

        # Формування тексту картки з екрануванням для Markdown
        card_text = LEXICON.PRODUCT_CARD_TEMPLATE.format(
            name=escape_markdown(product.назва),
            department=escape_markdown(product.відділ),
            group=escape_markdown(product.група or ""),
            months_no_movement=escape_markdown(display_months),
            stock_sum=escape_markdown(display_stock_sum),
            available_qty=escape_markdown(display_available_qty),
            reserved_qty=escape_markdown(display_user_reserved_qty),
            reserved_sum=escape_markdown(f"{reserved_sum:.2f}" if isinstance(reserved_sum, (float, int)) else str(reserved_sum)),
        )

        keyboard = get_product_actions_kb(
            product.id,
            int_available_for_button,
            search_query=search_query,
        )

        sent_message: Message | None = None
        if message_id:
            try:
                sent_message = await bot.edit_message_text(
                    text=card_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=keyboard,
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise
        else:
            sent_message = await bot.send_message(chat_id, card_text, reply_markup=keyboard)

        return sent_message

    except Exception as e:
        logger.error(
            "Помилка відправки/редагування картки товару %s для %s: %s",
            product.id,
            user_id,
            e,
            exc_info=True,
        )
        await bot.send_message(chat_id, LEXICON.UNEXPECTED_ERROR)
        return None