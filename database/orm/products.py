# epicservice/database/orm/products.py

import asyncio
import logging
import re

import pandas as pd
from sqlalchemy import delete, func, select, update
from thefuzz import fuzz

from database.engine import async_session, sync_session
from database.models import Product

# Налаштовуємо логер для цього модуля
logger = logging.getLogger(__name__)


# --- Допоміжні приватні функції ---

def _extract_article(name_str: str) -> str | None:
    """
    Витягує артикул з початку рядка назви товару.
    """
    if not isinstance(name_str, str):
        name_str = str(name_str)
    match = re.match(r"^(\d{8,})", name_str.strip())
    return match.group(1) if match else None


def _normalize_value(value: any, is_float: bool = True) -> float | str:
    """
    Приводить значення до стандартизованого числового типу (float) або рядка.
    Видаляє всі символи, крім цифр та розділювача, замінює коми на крапки.
    """
    if pd.isna(value):
        return 0.0 if is_float else "0"

    s_value = str(value).replace(',', '.').strip()
    # Дозволяємо знаку мінус бути на початку рядка
    s_value = re.sub(r'[^0-9.-]', '', s_value)
    
    try:
        return float(s_value) if is_float else s_value
    except (ValueError, TypeError):
        return 0.0 if is_float else "0"


# --- Функції імпорту та оновлення даних ---

def _sync_smart_import(dataframe: pd.DataFrame) -> dict:
    """
    Синхронно виконує "розумний" імпорт товарів з DataFrame у базу даних.
    Тепер використовує "м'яке видалення" (деактивацію) та керує ціною.
    """
    try:
        df_columns_lower = {str(col).lower() for col in dataframe.columns}
        required_columns = {"в", "г", "н", "к"}
        
        if not required_columns.issubset(df_columns_lower):
            missing = required_columns - df_columns_lower
            logger.error(f"Помилка імпорту: відсутні обов'язкові колонки: {', '.join(missing)}.")
            return {}

        column_mapping = {
            "в": "відділ", "г": "група", "н": "назва", "к": "кількість",
            "м": "місяці_без_руху", "с": "сума_залишку", "ц": "ціна"
        }
        dataframe.rename(columns=lambda c: column_mapping.get(str(c).lower(), c), inplace=True)

        # --- ВИПРАВЛЕННЯ: Використовуємо None як прапорець ---
        has_months_column = "місяці_без_руху" in dataframe.columns

        file_articles_data = {}
        for _, row in dataframe.iterrows():
            if pd.notna(row["назва"]) and (article := _extract_article(row["назва"])):
                
                price = _normalize_value(row.get("ціна", 0.0))
                if price == 0.0:
                    quantity_val = _normalize_value(row.get("кількість", 0.0))
                    stock_sum = _normalize_value(row.get("сума_залишку", 0.0))
                    if quantity_val > 0:
                        price = stock_sum / quantity_val

                quantity_str = _normalize_value(row.get("кількість", "0"), is_float=False)
                final_stock_sum = float(_normalize_value(quantity_str, is_float=True)) * price

                months_value = None
                if has_months_column:
                    months_value = int(_normalize_value(row.get("місяці_без_руху", 0)))

                file_articles_data[article] = {
                    "назва": str(row["назва"]).strip(),
                    "відділ": int(row["відділ"]),
                    "група": str(row.get("група", "")).strip(),
                    "кількість": quantity_str,
                    "місяці_без_руху": months_value,
                    "сума_залишку": final_stock_sum,
                    "ціна": price,
                    "активний": True
                }

        file_articles = set(file_articles_data.keys())
        updated_count, added_count, deactivated_count, reactivated_count = 0, 0, 0, 0
        department_stats = {}

        with sync_session() as session:
            existing_products = {p.артикул: p for p in session.execute(select(Product)).scalars()}
            db_articles = set(existing_products.keys())

            articles_to_add = file_articles - db_articles
            articles_to_update = db_articles.intersection(file_articles)
            articles_to_deactivate = db_articles - file_articles

            if articles_to_deactivate:
                stmt = update(Product).where(
                    Product.артикул.in_(articles_to_deactivate), Product.активний == True
                ).values(активний=False)
                result = session.execute(stmt)
                deactivated_count = result.rowcount

            if articles_to_update:
                products_to_update_mappings = []
                for article in articles_to_update:
                    if not existing_products[article].активний:
                        reactivated_count += 1
                    
                    if file_articles_data[article]["ціна"] == 0.0 and existing_products[article].ціна > 0.0:
                        price = existing_products[article].ціна
                        file_articles_data[article]["ціна"] = price
                        quantity = float(_normalize_value(file_articles_data[article]["кількість"], is_float=True))
                        file_articles_data[article]["сума_залишку"] = quantity * price
                    
                    # --- ВИПРАВЛЕННЯ: Перевіряємо на None ---
                    if file_articles_data[article]["місяці_без_руху"] is None:
                        file_articles_data[article]["місяці_без_руху"] = existing_products[article].місяці_без_руху

                    update_data = {"id": existing_products[article].id, "артикул": article, **file_articles_data[article]}
                    products_to_update_mappings.append(update_data)
                
                if products_to_update_mappings:
                    session.bulk_update_mappings(Product, products_to_update_mappings)
                    updated_count = len(products_to_update_mappings)

            if articles_to_add:
                # Встановлюємо 0, якщо місяці не були вказані
                for article in articles_to_add:
                    if file_articles_data[article]["місяці_без_руху"] is None:
                        file_articles_data[article]["місяці_без_руху"] = 0
                products_to_add_objects = [Product(артикул=article, **file_articles_data[article]) for article in articles_to_add]
                if products_to_add_objects:
                    session.bulk_save_objects(products_to_add_objects)
                    added_count = len(products_to_add_objects)
            
            session.execute(update(Product).values(відкладено=0))
            session.commit()

            total_in_db = session.execute(select(func.count(Product.id)).where(Product.активний == True)).scalar_one()

            for data in file_articles_data.values():
                dep = data["відділ"]
                department_stats[dep] = department_stats.get(dep, 0) + 1
            
            return {
                'added': added_count, 'updated': updated_count,
                'deactivated': deactivated_count, 'reactivated': reactivated_count,
                'total_in_db': total_in_db, 'total_in_file': len(file_articles),
                'department_stats': department_stats
            }

    except Exception as e:
        logger.error(f"Помилка під час синхронного імпорту: {e}", exc_info=True)
        return {}


async def orm_smart_import(dataframe: pd.DataFrame) -> dict:
    """
    Асинхронна обгортка для запуску синхронної функції імпорту.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_smart_import, dataframe)


def _sync_subtract_collected_from_stock(dataframe: pd.DataFrame) -> dict:
    """
    Синхронно віднімає кількість зібраних товарів від залишків
    та перераховує суму залишку.
    """
    processed_count, not_found_count, error_count = 0, 0, 0
    with sync_session() as session:
        for _, row in dataframe.iterrows():
            article = str(row.get("артикул", "")).strip()
            if not article:
                continue

            product = session.execute(select(Product).where(Product.артикул == article)).scalar_one_or_none()
            if not product:
                not_found_count += 1
                logger.warning(f"Віднімання: товар з артикулом {article} не знайдено в БД.")
                continue

            try:
                current_stock = float(str(product.кількість).replace(',', '.'))
                quantity_to_subtract = float(str(row["кількість"]).replace(',', '.'))
                
                new_stock = current_stock - quantity_to_subtract
                price = product.ціна or 0.0
                new_stock_sum = new_stock * price

                session.execute(
                    update(Product)
                    .where(Product.id == product.id)
                    .values(
                        кількість=str(new_stock),
                        сума_залишку=new_stock_sum
                    )
                )
                processed_count += 1
            except (ValueError, TypeError) as e:
                error_count += 1
                logger.error(f"Помилка конвертації числа для артикула {article}: {e}")
                continue
        session.commit()
    return {'processed': processed_count, 'not_found': not_found_count, 'errors': error_count}


async def orm_subtract_collected(dataframe: pd.DataFrame) -> dict:
    """
    Асинхронна обгортка для запуску синхронної функції віднімання залишків.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_subtract_collected_from_stock, dataframe)


# --- Функції пошуку та отримання товарів ---

async def orm_find_products(search_query: str) -> list[Product]:
    """
    Виконує нечіткий пошук товарів у базі даних серед активних товарів.
    """
    async with async_session() as session:
        like_query = f"%{search_query}%"
        stmt = select(Product).where(
            Product.активний == True,
            (Product.назва.ilike(like_query)) | (Product.артикул.ilike(like_query))
        )
        result = await session.execute(stmt)
        candidates = result.scalars().all()

        if not candidates: return []

        scored_products = []
        search_query_lower = search_query.lower()

        for product in candidates:
            if search_query == product.артикул: article_score = 200
            else: article_score = fuzz.ratio(search_query, product.артикул) * 1.5

            name_lower = product.назва.lower()
            token_set_score = fuzz.token_set_ratio(search_query_lower, name_lower)
            partial_score = fuzz.partial_ratio(search_query_lower, name_lower)
            
            if name_lower.startswith(search_query_lower): name_score = 100
            else: name_score = (token_set_score * 0.7) + (partial_score * 0.3)

            final_score = max(article_score, name_score)

            if final_score > 65:
                scored_products.append((product, final_score))
        
        scored_products.sort(key=lambda x: x[1], reverse=True)
        return [product for product, score in scored_products[:15]]


async def orm_get_product_by_id(session, product_id: int, for_update: bool = False) -> Product | None:
    """
    Отримує один товар за його унікальним ідентифікатором (ID).
    """
    query = select(Product).where(Product.id == product_id)
    if for_update: query = query.with_for_update()
    result = await session.execute(query)
    return result.scalar_one_or_none()


# --- Функції для звітів ---

def orm_get_all_products_sync() -> list[Product]:
    """
    Синхронно отримує всі активні товари з бази даних для формування звіту.
    """
    with sync_session() as session:
        query = select(Product).where(Product.активний == True).order_by(Product.відділ, Product.назва)
        result = session.execute(query)
        return result.scalars().all()