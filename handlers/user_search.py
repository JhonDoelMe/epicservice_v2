# epicservice/handlers/user_search.py

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import SQLAlchemyError

from database.engine import async_session
from database.orm import orm_find_products, orm_get_product_by_id
from handlers.common import clean_previous_keyboard
# --- ЗМІНА: Імпортуємо back_to_main_menu для коректної навігації ---
from handlers.user.list_management import back_to_main_menu
from keyboards.inline import get_search_results_kb
from lexicon.lexicon import LEXICON
from utils.card_generator import send_or_edit_product_card

logger = logging.getLogger(__name__)
router = Router()

class SearchStates(StatesGroup):
    showing_results = State()


@router.message(F.text)
async def search_handler(message: Message, bot: Bot, state: FSMContext):
    """
    Обробник пошуку. Тепер видаляє клавіатуру з попереднього меню.
    """
    # Не скидаємо стан повністю, щоб зберегти main_message_id
    await state.set_state(None)
    
    search_query = message.text
    
    known_commands = {
        LEXICON.BUTTON_NEW_LIST, LEXICON.BUTTON_MY_LIST,
        LEXICON.BUTTON_ARCHIVE, LEXICON.BUTTON_ADMIN_PANEL,
    }
    if search_query.startswith("/") or search_query in known_commands:
        return

    try:
        await message.delete()
    except TelegramBadRequest:
        logger.warning("Не вдалося видалити пошуковий запит користувача.")

    if len(search_query) < 3:
        # Це тимчасове повідомлення, воно не повинно мати клавіатури
        await message.answer(LEXICON.SEARCH_TOO_SHORT, reply_markup=None)
        return
        
    try:
        # --- ОНОВЛЕНА ЛОГІКА: Прибираємо стару клавіатуру ---
        await clean_previous_keyboard(state, bot, message.chat.id)
        # --- КІНЕЦЬ ОНОВЛЕНОЇ ЛОГІКИ ---

        products = await orm_find_products(search_query)
        if not products:
            sent_message = await message.answer(LEXICON.SEARCH_NO_RESULTS, reply_markup=None)
            # Зберігаємо ID, щоб потім його можна було прибрати
            await state.update_data(main_message_id=sent_message.message_id)
            return
            
        if len(products) == 1:
            sent_message = await send_or_edit_product_card(bot, message.chat.id, message.from_user.id, products[0])
            if sent_message:
                await state.update_data(main_message_id=sent_message.message_id)
        else:
            await state.set_state(SearchStates.showing_results)
            await state.update_data(last_query=search_query)
            
            sent_message = await message.answer(
                LEXICON.SEARCH_MANY_RESULTS, 
                reply_markup=get_search_results_kb(products)
            )
            await state.update_data(main_message_id=sent_message.message_id)
            
    except SQLAlchemyError as e:
        logger.error("Помилка пошуку товарів для запиту '%s': %s", search_query, e)
        await message.answer(LEXICON.UNEXPECTED_ERROR)


@router.callback_query(F.data.startswith("product:"))
async def show_product_from_button(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.answer()
    try:
        product_id = int(callback.data.split(":", 1)[1])
        
        fsm_data = await state.get_data()
        last_query = fsm_data.get('last_query')
        
        async with async_session() as session:
            product = await orm_get_product_by_id(session, product_id)
            if product:
                # Редагуємо повідомлення зі списком результатів, перетворюючи його на картку
                sent_message = await send_or_edit_product_card(
                    bot=bot, 
                    chat_id=callback.message.chat.id, 
                    user_id=callback.from_user.id, 
                    product=product,
                    message_id=callback.message.message_id, # Редагуємо існуюче
                    search_query=last_query
                )
                if sent_message:
                    await state.update_data(main_message_id=sent_message.message_id)
            else:
                await callback.message.edit_text(LEXICON.PRODUCT_NOT_FOUND)
                
    except (ValueError, IndexError, SQLAlchemyError) as e:
        logger.error("Помилка БД при отриманні товару: %s", e)
        await callback.message.edit_text(LEXICON.UNEXPECTED_ERROR)


@router.callback_query(SearchStates.showing_results, F.data == "back_to_results")
async def back_to_results_handler(callback: CallbackQuery, state: FSMContext):
    fsm_data = await state.get_data()
    last_query = fsm_data.get('last_query')

    if not last_query:
        await back_to_main_menu(callback, state)
        await callback.answer("Помилка: запит не знайдено", show_alert=True)
        return

    products = await orm_find_products(last_query)
    
    await callback.message.edit_text(
        LEXICON.SEARCH_MANY_RESULTS,
        reply_markup=get_search_results_kb(products)
    )
    await state.update_data(main_message_id=callback.message.message_id)
    await callback.answer()