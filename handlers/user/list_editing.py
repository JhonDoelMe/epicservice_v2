# epicservice/handlers/user/list_editing.py

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from database.engine import async_session
from database.orm import (orm_delete_temp_list_item, orm_get_product_by_id,
                          orm_get_temp_list,
                          orm_update_temp_list_item_quantity)
# --- ЗМІНА: Імпортуємо потрібні хелпери ---
from handlers.common import clean_previous_keyboard
from handlers.user.list_management import _display_user_list
from keyboards.inline import get_list_for_editing_kb
from lexicon.lexicon import LEXICON

# Налаштовуємо логер
logger = logging.getLogger(__name__)

# Створюємо роутер
router = Router()


class ListEditingStates(StatesGroup):
    editing_list = State()
    waiting_for_new_quantity = State()


async def show_list_in_edit_mode(bot: Bot, chat_id: int, message_id: int, user_id: int, state: FSMContext):
    """
    Допоміжна функція для відображення списку в режимі редагування.
    """
    temp_list = await orm_get_temp_list(user_id)

    if not temp_list:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=LEXICON.EMPTY_LIST)
        except TelegramBadRequest:
            pass
        return

    department_id = temp_list[0].product.відділ
    header = f"{LEXICON.LIST_EDIT_MODE_TITLE} (Відділ: {department_id})\n\n{LEXICON.LIST_EDIT_PROMPT}"

    try:
        await bot.edit_message_text(
            text=header,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=get_list_for_editing_kb(temp_list)
        )
        # Оновлюємо ID, оскільки цей екран тепер головний
        await state.update_data(main_message_id=message_id)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.error("Помилка редагування повідомлення в режим редагування: %s", e)


@router.callback_query(F.data == "edit_list:start")
async def start_list_editing_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.set_state(ListEditingStates.editing_list)
    await show_list_in_edit_mode(bot, callback.message.chat.id, callback.message.message_id, callback.from_user.id, state)
    await callback.answer("Режим редагування увімкнено")


@router.callback_query(ListEditingStates.editing_list, F.data.startswith("edit_item:"))
async def edit_item_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        product_id = int(callback.data.split(":", 1)[1])
        async with async_session() as session:
            product = await orm_get_product_by_id(session, product_id)
            if not product:
                await callback.answer(LEXICON.PRODUCT_NOT_FOUND, show_alert=True)
                return

        await state.update_data(product_id=product.id)
        
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=LEXICON.BUTTON_CANCEL_INPUT, callback_data="edit_list:cancel_input")
        ]])
        
        await bot.edit_message_text(
            text=LEXICON.EDIT_ITEM_QUANTITY_PROMPT.format(product_name=product.назва),
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            reply_markup=cancel_kb,
            parse_mode=None
        )
        
        await state.set_state(ListEditingStates.waiting_for_new_quantity)
        await callback.answer()

    except Exception as e:
        logger.error("Помилка при виборі товару для редагування: %s", e, exc_info=True)
        await callback.answer(LEXICON.UNEXPECTED_ERROR, show_alert=True)


@router.callback_query(ListEditingStates.waiting_for_new_quantity, F.data == "edit_list:cancel_input")
async def cancel_quantity_input_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.set_state(ListEditingStates.editing_list)
    await show_list_in_edit_mode(bot, callback.message.chat.id, callback.message.message_id, callback.from_user.id, state)
    await callback.answer("Скасовано")


@router.message(ListEditingStates.waiting_for_new_quantity, F.text.isdigit())
async def process_new_quantity_handler(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    data = await state.get_data()
    product_id = data.get("product_id")
    edit_list_message_id = data.get("main_message_id") # Беремо ID звідси

    try:
        new_quantity = int(message.text)
        
        if new_quantity > 0:
            await orm_update_temp_list_item_quantity(user_id, product_id, new_quantity)
        else:
            await orm_delete_temp_list_item(user_id, product_id)

        await show_list_in_edit_mode(bot, message.chat.id, edit_list_message_id, user_id, state)
        
    except Exception as e:
        logger.error("Помилка при оновленні кількості: %s", e, exc_info=True)
        await message.answer(LEXICON.UNEXPECTED_ERROR)
    finally:
        await message.delete()
        await state.set_state(ListEditingStates.editing_list)


@router.callback_query(ListEditingStates.editing_list, F.data == "edit_list:finish")
async def finish_list_editing_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.set_state(None)
    
    # --- ЗМІНА: Видаляємо клавіатуру, а не повідомлення ---
    await callback.message.edit_reply_markup(reply_markup=None)
    
    await _display_user_list(bot, callback.message.chat.id, callback.from_user.id, state)
    
    await callback.answer("Редагування завершено")