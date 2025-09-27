# epicservice/database/orm/__init__.py

"""
Пакет ORM (Object-Relational Mapping).

Цей __init__.py файл збирає всі публічні ORM-функції з окремих модулів
(products, temp_lists, archives, users, reports) в єдиний простір імен `database.orm`.

Це дозволяє іншим частинам програми (наприклад, обробникам) імпортувати
будь-яку ORM-функцію напряму, не знаючи про її точне розташування у файлі:

    from database.orm import orm_find_products

Замість:

    from database.orm.products import orm_find_products

Такий підхід спрощує рефакторинг та підтримку коду.
"""

from .products import (
    orm_find_products, orm_get_all_products_sync, orm_get_product_by_id,
    orm_smart_import, orm_subtract_collected
)
from .temp_lists import (
    orm_add_item_to_temp_list, orm_clear_temp_list, orm_delete_temp_list_item,
    orm_get_all_temp_list_items_sync, orm_get_temp_list,
    orm_get_temp_list_department, orm_get_temp_list_item_quantity,
    orm_get_total_temp_reservation_for_product, orm_get_users_with_active_lists,
    orm_update_temp_list_item_quantity
)
from .archives import (
    orm_add_saved_list, orm_delete_all_saved_lists_sync,
    orm_delete_lists_older_than_sync, orm_get_all_collected_items_sync,
    orm_get_all_files_for_user, orm_get_user_lists_archive,
    orm_get_users_for_warning_sync, orm_get_users_with_archives,
    orm_update_reserved_quantity
)
from .users import (
    orm_upsert_user, orm_get_all_users_sync
)

# --- ЗМІНА ---
# ВИДАЛЕНО: Імпорти з модуля звітів, оскільки файл reports.py видалено
# from .reports import (
#     orm_get_stock_status_sync,
#     orm_get_collection_status_sync
# )
# --- КІНЕЦЬ ЗМІНИ ---

# Явно визначаємо, що саме буде експортуватися
__all__ = [
    # products
    "orm_find_products", "orm_get_product_by_id", "orm_smart_import",
    "orm_subtract_collected", "orm_get_all_products_sync",
    # temp_lists
    "orm_clear_temp_list", "orm_add_item_to_temp_list",
    "orm_delete_temp_list_item", "orm_get_temp_list",
    "orm_get_temp_list_department", "orm_get_temp_list_item_quantity",
    "orm_get_total_temp_reservation_for_product",
    "orm_get_all_temp_list_items_sync", "orm_get_users_with_active_lists",
    "orm_update_temp_list_item_quantity",
    # archives
    "orm_add_saved_list", "orm_update_reserved_quantity",
    "orm_get_user_lists_archive", "orm_get_all_files_for_user",
    "orm_get_users_with_archives", "orm_get_all_collected_items_sync",
    "orm_delete_all_saved_lists_sync", "orm_delete_lists_older_than_sync",
    "orm_get_users_for_warning_sync",
    # users
    "orm_upsert_user", "orm_get_all_users_sync",
    # --- ЗМІНА ---
    # ВИДАЛЕНО: Назви функцій звітів зі списку __all__
    # "orm_get_stock_status_sync", "orm_get_collection_status_sync"
]
# --- КІНЕЦЬ ЗМІНИ ---