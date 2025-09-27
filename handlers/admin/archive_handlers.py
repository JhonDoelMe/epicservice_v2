# epicservice/handlers/admin/archive_handlers.py

import logging
import os
import zipfile
from datetime import datetime
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile
from sqlalchemy.exc import SQLAlchemyError

from config import ADMIN_IDS, ARCHIVES_PATH
from database.orm import (orm_get_all_files_for_user,
                          orm_get_user_lists_archive,
                          orm_get_users_with_archives)
from handlers.admin.core import _show_admin_panel
from keyboards.inline import get_archive_kb, get_users_with_archives_kb
from lexicon.lexicon import LEXICON

# Налаштовуємо логер
logger = logging.getLogger(__name__)

# Створюємо роутер
router = Router()
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


async def _pack_user_files_to_zip(user_id: int) -> Optional[str]:
    """
    Пакує всі збережені файли користувача в один ZIP-архів.
    """
    try:
        file_paths = await orm_get_all_files_for_user(user_id)
        if not file_paths:
            return None

        os.makedirs(ARCHIVES_PATH, exist_ok=True)
        zip_filename = f"user_{user_id}_archive_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
        zip_path = os.path.join(ARCHIVES_PATH, zip_filename)

        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file_path in file_paths:
                if os.path.exists(file_path):
                    zipf.write(file_path, os.path.basename(file_path))

        return zip_path
    except Exception as e:
        logger.error("Помилка створення ZIP-архіву для користувача %s: %s", user_id, e, exc_info=True)
        return None


# --- Сценарій перегляду архівів користувачів ---

@router.callback_query(F.data == "admin:user_archives")
async def show_users_archives_list(callback: CallbackQuery, state: FSMContext):
    """
    Показує адміністратору список користувачів, які мають збережені архіви.
    """
    try:
        users = await orm_get_users_with_archives()
        if not users:
            await callback.answer(LEXICON.NO_USERS_WITH_ARCHIVES, show_alert=True)
            return

        await callback.message.edit_text(
            LEXICON.CHOOSE_USER_TO_VIEW_ARCHIVE,
            reply_markup=get_users_with_archives_kb(users)
        )
        await state.update_data(main_message_id=callback.message.message_id)
        await callback.answer()
    except SQLAlchemyError as e:
        logger.error("Помилка БД при отриманні списку користувачів з архівами: %s", e, exc_info=True)
        await callback.answer(LEXICON.UNEXPECTED_ERROR, show_alert=True)


@router.callback_query(F.data.startswith("admin:view_user:"))
async def view_user_archive(callback: CallbackQuery, state: FSMContext):
    """
    Показує детальний архів обраного користувача.
    """
    try:
        user_id = int(callback.data.split(":")[-1])
        archived_lists = await orm_get_user_lists_archive(user_id)

        if not archived_lists:
            await callback.answer(LEXICON.USER_HAS_NO_ARCHIVES, show_alert=True)
            await show_users_archives_list(callback, state)
            return

        response_lines = [LEXICON.USER_ARCHIVE_TITLE.format(user_id=user_id)]
        for i, lst in enumerate(archived_lists, 1):
            created_date = lst.created_at.strftime("%d.%m.%Y о %H:%M")
            response_lines.append(
                LEXICON.ARCHIVE_ITEM.format(i=i, file_name=lst.file_name, created_date=created_date)
            )

        await callback.message.edit_text(
            "\n".join(response_lines),
            reply_markup=get_archive_kb(user_id, is_admin_view=True)
        )
        await state.update_data(main_message_id=callback.message.message_id)
        await callback.answer()
    except (ValueError, IndexError, SQLAlchemyError) as e:
        logger.error("Помилка при перегляді архіву користувача: %s", e, exc_info=True)
        await callback.answer(LEXICON.UNEXPECTED_ERROR, show_alert=True)


@router.callback_query(F.data.startswith("download_zip:"))
async def download_zip_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """
    Обробляє запит на пакування та відправку ZIP-архіву.
    """
    zip_path = None
    try:
        user_id = int(callback.data.split(":")[-1])
        # --- ОНОВЛЕНО: Редагуємо повідомлення і прибираємо клавіатуру ---
        await callback.message.edit_text(LEXICON.PACKING_ARCHIVE.format(user_id=user_id), reply_markup=None)

        zip_path = await _pack_user_files_to_zip(user_id)
        if not zip_path:
            await callback.answer(LEXICON.NO_FILES_TO_ARCHIVE, show_alert=True)
            # Повертаємо до попереднього меню (перегляд архіву)
            await view_user_archive(callback, state)
            return

        await bot.send_document(
            chat_id=callback.from_user.id,
            document=FSInputFile(zip_path),
            caption=LEXICON.ZIP_ARCHIVE_CAPTION.format(user_id=user_id)
        )
        
        # --- ОНОВЛЕНО: Видаляємо тимчасове повідомлення і показуємо нове меню ---
        await callback.message.delete()
        await _show_admin_panel(callback, state, bot)
        await callback.answer()

    except (ValueError, IndexError) as e:
        logger.error("Некоректний callback_data для завантаження ZIP: %s", callback.data, exc_info=True)
        await callback.answer(LEXICON.UNEXPECTED_ERROR, show_alert=True)
    except Exception as e:
        await callback.answer(LEXICON.ZIP_ERROR.format(error=str(e)), show_alert=True)
        # Якщо сталася помилка, все одно показуємо головне меню
        await _show_admin_panel(callback, state, bot)
    finally:
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)