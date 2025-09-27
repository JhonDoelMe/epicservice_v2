# epicservice/handlers/user/list_saving.py

import logging
import os

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile
from sqlalchemy.exc import SQLAlchemyError

from config import ADMIN_IDS
from database.engine import async_session
from keyboards.inline import get_admin_main_kb, get_user_main_kb
from lexicon.lexicon import LEXICON
from utils.list_processor import process_and_save_list

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "save_list")
async def save_list_callback(callback: CallbackQuery, bot: Bot, state: FSMContext):
    """
    Обробляє запит на збереження списку, тепер з коректним керуванням UI.
    """
    user_id = callback.from_user.id
    await callback.message.edit_text(LEXICON.SAVING_LIST_PROCESS, reply_markup=None)
    
    main_list_path = None
    surplus_list_path = None
    
    try:
        async with async_session() as session:
            async with session.begin():
                main_list_path, surplus_list_path = await process_and_save_list(session, user_id)

        # Видаляємо повідомлення "Зберігаю..."
        await callback.message.delete()
        
        # Надсилаємо файли та інформаційні повідомлення
        if not main_list_path and not surplus_list_path:
            await bot.send_message(user_id, LEXICON.EMPTY_LIST)
        else:
            if main_list_path:
                await bot.send_document(user_id, FSInputFile(main_list_path), caption=LEXICON.MAIN_LIST_SAVED)
            if surplus_list_path:
                await bot.send_document(user_id, FSInputFile(surplus_list_path), caption=LEXICON.SURPLUS_LIST_CAPTION)

        await callback.answer(LEXICON.PROCESSING_COMPLETE, show_alert=True)

        user = callback.from_user
        kb = get_admin_main_kb() if user.id in ADMIN_IDS else get_user_main_kb()
        text = LEXICON.CMD_START_ADMIN if user.id in ADMIN_IDS else LEXICON.CMD_START_USER
        
        # Надсилаємо нове головне меню і зберігаємо його ID
        sent_message = await bot.send_message(user_id, text, reply_markup=kb)
        await state.update_data(main_message_id=sent_message.message_id)

    except (SQLAlchemyError, ValueError) as e:
        logger.error("Помилка транзакції при збереженні списку для %s: %s", user_id, e, exc_info=True)
        await callback.message.answer(LEXICON.TRANSACTION_ERROR)
    except Exception as e:
        logger.error("Неочікувана помилка при збереженні списку для %s: %s", user_id, e, exc_info=True)
        await callback.message.answer(LEXICON.UNEXPECTED_ERROR)
    finally:
        if main_list_path and os.path.exists(main_list_path):
            os.remove(main_list_path)
        if surplus_list_path and os.path.exists(surplus_list_path):
            os.remove(surplus_list_path)