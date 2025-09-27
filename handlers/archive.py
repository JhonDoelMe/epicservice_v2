# epicservice/handlers/archive.py

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.exc import SQLAlchemyError

from database.orm import orm_get_user_lists_archive
# --- ЗМІНА: Імпортуємо потрібні хелпери ---
from handlers.user.list_management import back_to_main_menu
from keyboards.inline import get_archive_kb
from lexicon.lexicon import LEXICON

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == "main:archive")
async def show_archive_handler(callback: CallbackQuery, state: FSMContext):
    """
    Обробник для кнопки '🗂️ Архів списків'.
    Тепер коректно редагує повідомлення та оновлює стан.
    """
    user_id = callback.from_user.id
    
    try:
        logger.info("Користувач %s запитує свій архів.", user_id)
        archived_lists = await orm_get_user_lists_archive(user_id)

        if not archived_lists:
            await callback.answer(LEXICON.NO_ARCHIVED_LISTS, show_alert=True)
            return

        response_text = [LEXICON.ARCHIVE_TITLE]
        for i, lst in enumerate(archived_lists, 1):
            created_date = lst.created_at.strftime("%d.%m.%Y о %H:%M")
            response_text.append(
                LEXICON.ARCHIVE_ITEM.format(
                    i=i, 
                    file_name=lst.file_name, 
                    created_date=created_date
                )
            )
        
        await callback.message.edit_text(
            "\n".join(response_text), 
            reply_markup=get_archive_kb(user_id)
        )
        # Оновлюємо ID головного повідомлення
        await state.update_data(main_message_id=callback.message.message_id)
        await callback.answer()
        
    except SQLAlchemyError as e:
        logger.error("Помилка БД при отриманні архіву для %s: %s", user_id, e, exc_info=True)
        await callback.message.answer(LEXICON.UNEXPECTED_ERROR)
    except Exception as e:
        logger.error("Неочікувана помилка при перегляді архіву %s: %s", user_id, e, exc_info=True)
        await callback.message.answer(LEXICON.UNEXPECTED_ERROR)