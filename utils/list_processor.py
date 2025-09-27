# epicservice/utils/list_processor.py

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from config import ARCHIVES_PATH
from database.orm import (orm_add_saved_list, orm_clear_temp_list,
                          orm_get_product_by_id, orm_get_temp_list,
                          orm_update_reserved_quantity)

logger = logging.getLogger(__name__)


async def _save_list_to_excel(
    items: List[Dict[str, Any]],
    user_id: int,
    department_id: Optional[int],
    total_sum: float,
    prefix: str = ""
) -> Optional[str]:
    """
    Зберігає список товарів у файл Excel, додаючи підсумкові дані.
    """
    if not items:
        return None
    try:
        timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M")
        
        base_name = department_id if department_id is not None else "list"
        file_name = f"{prefix}{base_name}_{timestamp}.xlsx"
        
        archive_dir = os.path.join(ARCHIVES_PATH, f"user_{user_id}")
        os.makedirs(archive_dir, exist_ok=True)
        file_path = os.path.join(archive_dir, file_name)

        df = pd.DataFrame(items)
        
        # --- НОВИЙ БЛОК: Додавання підсумкових рядків ---
        summary_df = pd.DataFrame([
            {"Артикул": "", "Кількість": ""},  # Порожній рядок для відступу
            {"Артикул": "К-ть артикулів:", "Кількість": len(df)},
            {"Артикул": "Зібрано на суму:", "Кількість": f"{total_sum:.2f} грн"}
        ])
        
        # Об'єднуємо основні дані з підсумковими
        df_final = pd.concat([df, summary_df], ignore_index=True)
        # --- КІНЕЦЬ НОВОГО БЛОКУ ---

        df_final.to_excel(file_path, index=False, header=['Артикул', 'Кількість'])
        
        logger.info("Файл успішно збережено: %s", file_path)
        return file_path
    except Exception as e:
        logger.error("Помилка збереження Excel файлу для користувача %s: %s", user_id, e, exc_info=True)
        return None


async def process_and_save_list(
    session: AsyncSession,
    user_id: int
) -> Tuple[Optional[str], Optional[str]]:
    """
    Централізована функція для обробки та збереження тимчасового списку.
    """
    temp_list = await orm_get_temp_list(user_id)
    if not temp_list:
        return None, None

    department_id = temp_list[0].product.відділ

    in_stock_items, surplus_items = [], []
    reservation_updates = []
    
    # --- НОВИЙ БЛОК: Розрахунок сум ---
    total_in_stock_sum = 0.0
    total_surplus_sum = 0.0
    # --- КІНЕЦЬ НОВОГО БЛОКУ ---

    for item in temp_list:
        product = await orm_get_product_by_id(session, item.product_id, for_update=True)
        if not product:
            continue

        try:
            stock_qty = float(str(product.кількість).replace(',', '.'))
        except (ValueError, TypeError):
            stock_qty = 0

        available = stock_qty - (product.відкладено or 0)
        reservation_updates.append({"product_id": product.id, "quantity": item.quantity})
        
        price = product.ціна or 0.0

        if item.quantity <= available:
            in_stock_items.append({"Артикул": product.артикул, "Кількість": item.quantity})
            total_in_stock_sum += item.quantity * price
        else:
            if available > 0:
                in_stock_items.append({"Артикул": product.артикул, "Кількість": available})
                total_in_stock_sum += available * price
            
            surplus_quantity = item.quantity - available
            surplus_items.append({"Артикул": product.артикул, "Кількість": surplus_quantity})
            total_surplus_sum += surplus_quantity * price


    if reservation_updates:
        await orm_update_reserved_quantity(session, reservation_updates)

    # Передаємо розраховані суми у функцію збереження
    main_list_path = await _save_list_to_excel(in_stock_items, user_id, department_id, total_in_stock_sum)
    surplus_list_path = await _save_list_to_excel(surplus_items, user_id, department_id, total_surplus_sum, "лишки_")

    if main_list_path and in_stock_items:
        # Зберігаємо article_name для сумісності зі старими звітами
        db_items = [{"article_name": p.product.назва, "quantity": p.quantity} for p in temp_list]
        await orm_add_saved_list(session, user_id, os.path.basename(main_list_path), main_list_path, db_items)

    await orm_clear_temp_list(user_id)

    return main_list_path, surplus_list_path