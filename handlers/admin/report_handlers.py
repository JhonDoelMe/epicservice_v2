# epicservice/handlers/admin/report_handlers.py

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Optional

import pandas as pd
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
# --- ЗМІНА: Імпортуємо StorageKey ---
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from sqlalchemy.exc import SQLAlchemyError

from config import ADMIN_IDS, ARCHIVES_PATH
from database.orm import (orm_get_all_collected_items_sync,
                          orm_get_all_products_sync,
                          orm_get_all_temp_list_items_sync,
                          orm_get_users_with_active_lists,
                          orm_subtract_collected)
from handlers.admin.core import _show_admin_panel
from keyboards.inline import get_admin_lock_kb
from lexicon.lexicon import LEXICON
from utils.force_save_helper import force_save_user_list

# Налаштовуємо логер
logger = logging.getLogger(__name__)

# Створюємо роутер
router = Router()
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


class AdminReportStates(StatesGroup):
    waiting_for_subtract_file = State()
    lock_confirmation = State()


def _create_stock_report_sync() -> Optional[str]:
    try:
        products = orm_get_all_products_sync()
        temp_list_items = orm_get_all_temp_list_items_sync()
        
        temp_reservations = {}
        for item in temp_list_items:
            temp_reservations[item.product_id] = temp_reservations.get(item.product_id, 0) + item.quantity

        report_data = []
        for product in products:
            try:
                stock_qty = float(str(product.кількість).replace(',', '.'))
            except (ValueError, TypeError):
                stock_qty = 0
            
            reserved = (product.відкладено or 0) + temp_reservations.get(product.id, 0)
            available = stock_qty - reserved
            
            available_sum = available * (product.ціна or 0.0)

            report_data.append({
                "Відділ": product.відділ,
                "Група": product.група,
                "Назва": product.назва,
                "Залишок (кількість)": int(available) if available == int(available) else available,
                "Сума залишку (грн)": round(available_sum, 2)
            })
            
        df = pd.DataFrame(report_data)
        os.makedirs(ARCHIVES_PATH, exist_ok=True)
        report_path = os.path.join(ARCHIVES_PATH, f"stock_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
        df.to_excel(report_path, index=False)
        return report_path
    except Exception as e:
        logger.error("Помилка створення звіту про залишки: %s", e, exc_info=True)
        return None


def _parse_and_validate_subtract_file(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    try:
        df_columns_lower = {str(c).lower() for c in df.columns}
        if {"назва", "кількість"}.issubset(df_columns_lower):
            df.rename(columns={col: str(col).lower() for col in df.columns}, inplace=True)
            df_prepared = df[['назва', 'кількість']].copy()
            df_prepared['артикул'] = df_prepared['назва'].astype(str).str.extract(r'(\d{8,})')
            df_prepared = df_prepared.dropna(subset=['артикул'])
            if pd.to_numeric(df_prepared['кількість'], errors='coerce').notna().all():
                return df_prepared[['артикул', 'кількість']]

        if len(df.columns) == 2:
            header_as_data = pd.DataFrame([df.columns.values], columns=['артикул', 'кількість'])
            df.columns = ['артикул', 'кількість']
            df_simple = pd.concat([header_as_data, df], ignore_index=True)
            
            if pd.to_numeric(df_simple['артикул'], errors='coerce').notna().all() and \
               pd.to_numeric(df_simple['кількість'], errors='coerce').notna().all():
                return df_simple[['артикул', 'кількість']]
    except Exception as e:
        logger.error(f"Помилка парсингу файлу для віднімання: {e}")

    return None


async def proceed_with_stock_export(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.answer(LEXICON.EXPORTING_STOCK)
    await callback.message.edit_text("Формую звіт по залишкам...", reply_markup=None)
    
    loop = asyncio.get_running_loop()
    report_path = await loop.run_in_executor(None, _create_stock_report_sync)
    
    await callback.message.delete()

    if not report_path:
        await bot.send_message(callback.from_user.id, LEXICON.STOCK_REPORT_ERROR)
    else:
        try:
            await bot.send_document(
                chat_id=callback.from_user.id,
                document=FSInputFile(report_path),
                caption=LEXICON.STOCK_REPORT_CAPTION
            )
        finally:
            if os.path.exists(report_path): os.remove(report_path)
    
    await _show_admin_panel(callback, state, bot)


async def proceed_with_collected_export(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.answer(LEXICON.COLLECTED_REPORT_PROCESSING)
    await callback.message.edit_text("Формую зведений звіт...", reply_markup=None)
    
    loop = asyncio.get_running_loop()
    try:
        collected_items = await loop.run_in_executor(None, orm_get_all_collected_items_sync)
        await callback.message.delete()
        
        if not collected_items:
            await bot.send_message(callback.from_user.id, LEXICON.COLLECTED_REPORT_EMPTY)
        else:
            df = pd.DataFrame(collected_items)
            df.rename(
                columns={"department": "Відділ", "group": "Група", "name": "Назва", "quantity": "Кількість"},
                inplace=True
            )
            os.makedirs(ARCHIVES_PATH, exist_ok=True)
            report_path = os.path.join(ARCHIVES_PATH, f"collected_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
            df.to_excel(report_path, index=False)
            await bot.send_document(
                chat_id=callback.from_user.id,
                document=FSInputFile(report_path),
                caption=LEXICON.COLLECTED_REPORT_CAPTION
            )
            os.remove(report_path)
        
        await _show_admin_panel(callback, state, bot)
    except Exception as e:
        logger.error("Помилка створення зведеного звіту: %s", e, exc_info=True)
        await bot.send_message(callback.from_user.id, LEXICON.UNEXPECTED_ERROR)


@router.callback_query(F.data == "admin:export_stock")
async def export_stock_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    active_users = await orm_get_users_with_active_lists()
    if not active_users:
        await proceed_with_stock_export(callback, bot, state)
        return
    users_info = "\n".join([f"- Користувач `{user_id}` (позицій: {count})" for user_id, count in active_users])
    await state.update_data(action_to_perform='export_stock', locked_user_ids=[uid for uid, _ in active_users])
    await state.set_state(AdminReportStates.lock_confirmation)
    await callback.message.edit_text(LEXICON.ACTIVE_LISTS_BLOCK.format(users_info=users_info), reply_markup=get_admin_lock_kb('export_stock'))
    await callback.answer("Дію заблоковано", show_alert=True)


@router.callback_query(F.data == "admin:export_collected")
async def export_collected_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    active_users = await orm_get_users_with_active_lists()
    if not active_users:
        await proceed_with_collected_export(callback, bot, state)
        return
    users_info = "\n".join([f"- Користувач `{user_id}` (позицій: {count})" for user_id, count in active_users])
    await state.update_data(action_to_perform='export_collected', locked_user_ids=[uid for uid, _ in active_users])
    await state.set_state(AdminReportStates.lock_confirmation)
    await callback.message.edit_text(LEXICON.ACTIVE_LISTS_BLOCK.format(users_info=users_info), reply_markup=get_admin_lock_kb('export_collected'))
    await callback.answer("Дію заблоковано", show_alert=True)


@router.callback_query(AdminReportStates.lock_confirmation, F.data.startswith("lock:notify:"))
async def handle_report_lock_notify(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    for user_id in data.get('locked_user_ids', []):
        try:
            await bot.send_message(user_id, LEXICON.USER_SAVE_LIST_NOTIFICATION)
        except Exception as e:
            logger.warning("Не вдалося надіслати сповіщення користувачу %s: %s", user_id, e)
    await callback.answer(LEXICON.NOTIFICATIONS_SENT, show_alert=True)


@router.callback_query(AdminReportStates.lock_confirmation, F.data.startswith("lock:force_save:"))
async def handle_report_lock_force_save(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.edit_text("Почав примусове збереження списків...")
    data = await state.get_data()
    user_ids, action = data.get('locked_user_ids', []), data.get('action_to_perform')
    
    # --- ВИПРАВЛЕНО: Створюємо коректний FSMContext для кожного користувача ---
    results = []
    for user_id in user_ids:
        user_state_key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
        user_state = FSMContext(storage=state.storage, key=user_state_key)
        results.append(await force_save_user_list(user_id, bot, user_state))
    
    all_saved_successfully = all(results)
    
    if not all_saved_successfully:
        await callback.message.edit_text("Під час примусового збереження виникли помилки. Спробуйте пізніше.")
        await state.set_state(None)
        return
    await callback.answer("Всі списки успішно збережено!", show_alert=True)
    if action == 'export_stock':
        await proceed_with_stock_export(callback, bot, state)
    elif action == 'export_collected':
        await proceed_with_collected_export(callback, bot, state)
    await state.set_state(None)


@router.callback_query(F.data == "admin:subtract_collected")
async def start_subtract_handler(callback: CallbackQuery, state: FSMContext):
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=LEXICON.BUTTON_BACK_TO_ADMIN_PANEL,
            callback_data="admin:main"
        )
    ]])
    await callback.message.edit_text(LEXICON.SUBTRACT_PROMPT, reply_markup=back_kb)
    await state.set_state(AdminReportStates.waiting_for_subtract_file)
    await state.update_data(main_message_id=callback.message.message_id)
    await callback.answer()


@router.message(AdminReportStates.waiting_for_subtract_file, F.document)
async def process_subtract_file(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await bot.delete_message(message.chat.id, data.get("main_message_id"))
    await state.clear()
    
    await message.answer(LEXICON.SUBTRACT_PROCESSING)
    temp_file_path = f"temp_subtract_{message.from_user.id}.tmp"
    
    try:
        await bot.download(message.document, destination=temp_file_path)
        df = await asyncio.to_thread(pd.read_excel, temp_file_path)
        
        standardized_df = _parse_and_validate_subtract_file(df)
        
        if standardized_df is None:
            await message.answer(LEXICON.SUBTRACT_INVALID_COLUMNS)
        else:
            result = await orm_subtract_collected(standardized_df)
            report_text = "\n".join([
                LEXICON.SUBTRACT_REPORT_TITLE,
                LEXICON.SUBTRACT_REPORT_PROCESSED.format(processed=result['processed']),
                LEXICON.SUBTRACT_REPORT_NOT_FOUND.format(not_found=result['not_found']),
                LEXICON.SUBTRACT_REPORT_ERROR.format(errors=result['errors']),
            ])
            await message.answer(report_text)
            
    except SQLAlchemyError as e:
        logger.critical("Помилка БД під час віднімання залишків: %s", e, exc_info=True)
        await message.answer(LEXICON.IMPORT_SYNC_ERROR.format(error=str(e)))
    except Exception as e:
        logger.error("Помилка обробки файлу для віднімання: %s", e, exc_info=True)
        await message.answer(LEXICON.IMPORT_CRITICAL_READ_ERROR.format(error=str(e)))
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        await _show_admin_panel(message, state, bot)