# epicservice/handlers/user/item_addition.py

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database.engine import async_session
from database.orm import (orm_add_item_to_temp_list, orm_get_product_by_id,
                          orm_get_temp_list_department,
                          orm_get_total_temp_reservation_for_product)
from keyboards.inline import get_quantity_selector_kb
from lexicon.lexicon import LEXICON
from utils.card_generator import send_or_edit_product_card

logger = logging.getLogger(__name__)
router = Router()


class ItemAdditionStates(StatesGroup):
    waiting_for_manual_quantity = State()


async def _add_item_logic(user_id: int, product_id: int, quantity: int, bot: Bot, callback: CallbackQuery):
    """
    Уніфікована логіка додавання товару до списку.
    """
    try:
        async with async_session() as session:
            product = await orm_get_product_by_id(session, product_id)
            if not product:
                if callback.id != "fake_callback": # Перевіряємо, чи callback справжній
                    await callback.answer(LEXICON.PRODUCT_NOT_FOUND, show_alert=True)
                return

            allowed_department = await orm_get_temp_list_department(user_id)
            if allowed_department is not None and product.відділ != allowed_department:
                error_msg = LEXICON.DEPARTMENT_MISMATCH.format(department=allowed_department)
                if callback.id == "fake_callback":
                    # Для ручного вводу краще надіслати повідомлення, а не спливаюче вікно
                    await bot.send_message(callback.message.chat.id, error_msg)
                else:
                    await callback.answer(error_msg, show_alert=True)
                return

            await orm_add_item_to_temp_list(user_id, product_id, quantity)
            logger.info("Користувач %s додав товар ID %s (кількість: %s) до списку.", user_id, product_id, quantity)

            # --- ВИПРАВЛЕННЯ: Відповідаємо на callback, тільки якщо він справжній ---
            if callback.id != "fake_callback":
                await callback.answer(f"✅ Додано {quantity} шт.")
            
            # Оновлюємо картку товару в будь-якому випадку
            await send_or_edit_product_card(bot, callback.message.chat.id, user_id, product, callback.message.message_id)

    except Exception as e:
        logger.error("Неочікувана помилка додавання товару для %s: %s", user_id, e, exc_info=True)
        if callback.id != "fake_callback":
            await callback.answer(LEXICON.UNEXPECTED_ERROR, show_alert=True)
        else:
            await bot.send_message(callback.message.chat.id, LEXICON.UNEXPECTED_ERROR)


@router.callback_query(F.data.startswith("add_all:"))
async def add_all_callback(callback: CallbackQuery, bot: Bot):
    """Обробляє натискання на кнопку 'Додати все'."""
    user_id = callback.from_user.id
    try:
        _, product_id_str, quantity_str = callback.data.split(":")
        product_id, quantity = int(product_id_str), int(quantity_str)
        await _add_item_logic(user_id, product_id, quantity, bot, callback)
    except (ValueError, IndexError) as e:
        logger.error("Помилка обробки callback 'add_all': %s", callback.data, exc_info=True)
        await callback.answer(LEXICON.UNEXPECTED_ERROR, show_alert=True)


@router.callback_query(F.data.startswith("select_quantity:"))
async def show_quantity_selector(callback: CallbackQuery, bot: Bot):
    """Показує екран вибору кількості з лічильником."""
    try:
        product_id = int(callback.data.split(":")[1])
        user_id = callback.from_user.id
        
        async with async_session() as session:
            product = await orm_get_product_by_id(session, product_id)
            if not product:
                await callback.answer(LEXICON.PRODUCT_NOT_FOUND, show_alert=True)
                return
        
        total_temp_reserved = await orm_get_total_temp_reservation_for_product(product.id)
        stock_quantity = float(str(product.кількість).replace(',', '.'))
        permanently_reserved = product.відкладено or 0
        max_qty = int(stock_quantity - permanently_reserved - total_temp_reserved)

        await bot.edit_message_reply_markup(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            reply_markup=get_quantity_selector_kb(product_id, 1, max_qty)
        )
        await callback.answer()

    except (ValueError, IndexError, Exception) as e:
        logger.error("Помилка показу селектора кількості: %s", e, exc_info=True)
        await callback.answer(LEXICON.UNEXPECTED_ERROR, show_alert=True)


@router.callback_query(F.data.startswith("qty_update:"))
async def update_quantity_selector(callback: CallbackQuery, bot: Bot):
    """Обробляє натискання на [+] та [-] і оновлює клавіатуру."""
    try:
        _, product_id_str, action, current_qty_str, max_qty_str = callback.data.split(":")
        product_id, current_qty, max_qty = int(product_id_str), int(current_qty_str), int(max_qty_str)

        if action == "plus":
            new_qty = min(current_qty + 1, max_qty)
        elif action == "minus":
            new_qty = max(current_qty - 1, 1)
        else:
            new_qty = current_qty

        if new_qty == current_qty:
            await callback.answer()
            return

        await bot.edit_message_reply_markup(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            reply_markup=get_quantity_selector_kb(product_id, new_qty, max_qty)
        )
        await callback.answer()

    except (ValueError, IndexError, TelegramBadRequest) as e:
        logger.warning("Помилка оновлення лічильника: %s", e)
        await callback.answer()


@router.callback_query(F.data.startswith("add_confirm:"))
async def confirm_add_callback(callback: CallbackQuery, bot: Bot):
    """Обробляє натискання на центральну кнопку підтвердження."""
    user_id = callback.from_user.id
    try:
        _, product_id_str, quantity_str = callback.data.split(":")
        product_id, quantity = int(product_id_str), int(quantity_str)
        await _add_item_logic(user_id, product_id, quantity, bot, callback)
    except (ValueError, IndexError) as e:
        logger.error("Помилка обробки callback 'add_confirm': %s", callback.data, exc_info=True)
        await callback.answer(LEXICON.UNEXPECTED_ERROR, show_alert=True)


@router.callback_query(F.data.startswith("qty_manual_input:"))
async def manual_input_callback(callback: CallbackQuery, state: FSMContext):
    """Запитує у користувача кількість для ручного вводу."""
    try:
        product_id = int(callback.data.split(":")[1])
        await state.set_state(ItemAdditionStates.waiting_for_manual_quantity)
        await state.update_data(product_id=product_id, message_id=callback.message.message_id)
        
        await callback.message.edit_text(
            f"{callback.message.text}\n\n*Введіть потрібну кількість та надішліть повідомлення.*",
            reply_markup=None
        )
        await callback.answer("Чекаю на ваше повідомлення...")
    except (ValueError, IndexError) as e:
        logger.error("Помилка обробки callback 'qty_manual_input': %s", e, exc_info=True)
        await callback.answer(LEXICON.UNEXPECTED_ERROR, show_alert=True)


@router.message(ItemAdditionStates.waiting_for_manual_quantity, F.text.isdigit())
async def process_manual_quantity(message: Message, state: FSMContext, bot: Bot):
    """Обробляє кількість, введену вручну."""
    user_id = message.from_user.id
    state_data = await state.get_data()
    product_id = state_data.get("product_id")
    original_message_id = state_data.get("message_id")
    await state.clear()
    
    # Видаляємо повідомлення користувача з числом
    await message.delete()
    
    try:
        quantity = int(message.text)
        
        # --- ВИПРАВЛЕННЯ: Створюємо "фейковий" callback, але правильно ---
        # Він потрібен, щоб передати ID чату та повідомлення в _add_item_logic
        # для подальшого редагування картки товару.
        fake_callback = CallbackQuery(
            id="fake_callback",
            from_user=message.from_user,
            message=Message(
                message_id=original_message_id,
                chat=message.chat,
                date=message.date
            ),
            chat_instance=""
        )
        
        await _add_item_logic(user_id, product_id, quantity, bot, fake_callback)

    except Exception as e:
        logger.error("Помилка обробки ручного вводу кількості: %s", e, exc_info=True)
        await message.answer(LEXICON.UNEXPECTED_ERROR)