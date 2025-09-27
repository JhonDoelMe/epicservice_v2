# epicservice/handlers/admin/core.py

import asyncio
import logging
from typing import Union

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from database.orm import orm_delete_all_saved_lists_sync
# --- ЗМІНА: Імпортуємо наш хелпер ---
from handlers.common import clean_previous_keyboard
from keyboards.inline import get_admin_panel_kb, get_confirmation_kb
from lexicon.lexicon import LEXICON

# Налаштовуємо логер
logger = logging.getLogger(__name__)

# Створюємо роутер
router = Router()
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


class AdminCoreStates(StatesGroup):
    confirm_delete_all_lists = State()


# --- ОНОВЛЕНА ДОПОМІЖНА ФУНКЦІЯ ---
async def _show_admin_panel(event: Union[Message, CallbackQuery], state: FSMContext, bot: Bot):
    """
    Відображає головне меню адмін-панелі, керуючи станом повідомлення.
    """
    text = LEXICON.ADMIN_PANEL_GREETING
    reply_markup = get_admin_panel_kb()

    if isinstance(event, Message):
        # Якщо це нове повідомлення, прибираємо попередню клавіатуру
        await clean_previous_keyboard(state, bot, event.chat.id)
        sent_message = await event.answer(text, reply_markup=reply_markup)
        await state.update_data(main_message_id=sent_message.message_id)
    
    elif isinstance(event, CallbackQuery):
        try:
            # Намагаємось відредагувати поточне повідомлення
            await event.message.edit_text(text, reply_markup=reply_markup)
            await state.update_data(main_message_id=event.message.message_id)
        except TelegramBadRequest:
            # Якщо не вдалося, прибираємо клавіатуру зі старого і надсилаємо нове
            await clean_previous_keyboard(state, bot, event.message.chat.id)
            sent_message = await event.message.answer(text, reply_markup=reply_markup)
            await state.update_data(main_message_id=sent_message.message_id)


# --- Обробники входу в адмін-панель ---

@router.message(F.text == "👑 Адмін-панель")
async def admin_panel_handler(message: Message, state: FSMContext, bot: Bot):
    """
    Обробник для кнопки '👑 Адмін-панель'.
    """
    await _show_admin_panel(message, state, bot)


@router.callback_query(F.data == "admin:main")
async def admin_panel_callback_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """
    Обробник для кнопки 'Назад до адмін-панелі'.
    """
    await state.set_state(None) # Виходимо з будь-яких станів
    await _show_admin_panel(callback, state, bot)
    await callback.answer()


# --- Сценарій видалення всіх списків ---

@router.callback_query(F.data == "admin:delete_all_lists")
async def delete_all_lists_confirm_handler(callback: CallbackQuery, state: FSMContext):
    """
    Перший крок сценарію видалення. Запитує підтвердження.
    """
    await callback.message.edit_text(
        LEXICON.DELETE_ALL_LISTS_CONFIRM,
        reply_markup=get_confirmation_kb(
            "confirm_delete_all_yes", "admin:main" # Кнопка "Ні" тепер повертає в меню
        ),
    )
    await state.set_state(AdminCoreStates.confirm_delete_all_lists)
    await callback.answer()


@router.callback_query(AdminCoreStates.confirm_delete_all_lists, F.data == "confirm_delete_all_yes")
async def delete_all_lists_confirmed_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """
    Обробляє позитивне підтвердження та повертає до адмін-панелі.
    """
    await state.set_state(None)

    loop = asyncio.get_running_loop()
    deleted_count = await loop.run_in_executor(None, orm_delete_all_saved_lists_sync)

    if deleted_count > 0:
        await callback.answer(
            LEXICON.DELETE_ALL_LISTS_SUCCESS.format(count=deleted_count),
            show_alert=True
        )
    else:
        await callback.answer(LEXICON.NO_LISTS_TO_DELETE)

    # Повертаємо адміна до головного меню
    await _show_admin_panel(callback, state, bot)


# --- ВИДАЛЕНО ОБРОБНИК ДЛЯ "Ні", оскільки він тепер веде на "admin:main" ---