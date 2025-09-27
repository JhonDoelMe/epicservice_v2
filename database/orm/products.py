"""
Modified version of database/orm/products.py to ensure that all required
tables, including the ``users`` table from ``database.models``, are created when
initialising the database schema.

This file mirrors the original structure but imports the Base metadata from
``database.models`` and invokes its ``create_all`` method within
``ensure_schema``. This guarantees that the ``users`` table and other models
defined in ``database/models.py`` are created alongside the product‑related
tables defined here.

Additionally, this version augments the :class:`Product` model with a set of
Ukrainian‑named properties that proxy the existing English‑named attributes.
These accessors provide backward compatibility for parts of the codebase that
expect fields such as ``кількість`` or ``назва`` instead of ``qty`` and
``name``. Where there is no direct equivalent (e.g. ``відкладено``), sensible
defaults are returned (zero for reserved quantity, empty string for group).
"""

from __future__ import annotations

import enum
import json
import re
from datetime import datetime
from typing import Any, Iterable, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, declarative_base

from database.engine import async_session, sync_session

# NB: We import the canonical Product model from `database.models` to use in
# user‑facing queries (search and retrieval). This model defines Ukrainian
# field names such as ``артикул`` and ``назва`` and includes extra fields
# like ``група`` and ``відкладено``. Using it in search/get functions
# ensures that all user‑facing features receive full product details.
# Note: We intentionally do not import the Product model from database.models
# here because the PostgreSQL schema uses the English column names (article,
# dept_id, name, etc.). Attempting to query using the Ukrainian model leads
# to an UndefinedColumnError on columns like "артикул". The compatibility
# properties defined on this class (кількість, назва, тощо) allow the rest
# of the codebase to access fields using Ukrainian names while still storing
# data in the English‑named columns.

# Import the declarative base from database.models to include the User and other
# shared models. Using this Base ensures that ``ensure_schema`` will create
# tables defined in ``database/models.py`` as well as the ones defined below.
from database.models import Base as ModelsBase

# Local declarative base for product‑related tables. This remains separate
# because the original code defines its own base. We'll still create its
# tables in ``ensure_schema``.
Base = declarative_base()


# ------------------------------ Допоміжні типи -------------------------------

class PhotoStatus(str, enum.Enum):
    """Статус фото для модерації."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# --------------------------------- Моделі ------------------------------------

class Product(Base):
    """
    Товар і його залишок. Це «істина», з якою звіряються списки.

    Ключі:
      - dept_id + article — унікальна пара.

    Поля:
      - qty  — доступна кількість (ніколи < 0)
      - price — ціна за одиницю
      - months_no_move — скільки місяців без руху (0, якщо не рахуємо)
      - active — чи активний товар у довіднику

    This model stores product information using concise English attribute
    names. To support other parts of the application that expect
    Ukrainian‑named attributes (e.g. ``кількість``), this class defines
    properties that map the Ukrainian names to the underlying English ones.
    These properties also provide sensible defaults where the English model
    lacks a direct counterpart (for example, reserved quantity).
    """

    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    dept_id = Column(String(32), nullable=False)
    article = Column(String(32), nullable=False)
    name = Column(String(512), nullable=False, default="")

    qty = Column(Float, nullable=False, default=0.0)
    price = Column(Float, nullable=False, default=0.0)

    months_no_move = Column(Float, nullable=False, default=0.0)
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        UniqueConstraint("dept_id", "article", name="uq_products_dept_article"),
        CheckConstraint("qty >= 0", name="ck_products_qty_nonneg"),
        Index("ix_products_article", "article"),
        Index("ix_products_dept", "dept_id"),
        Index("ix_products_active", "active"),
    )

    # -------------------------------------------------------------------------
    # Ukrainian‑named accessors
    #
    # A number of modules within the project operate on instances of this
    # ``Product`` class using Ukrainian field names (e.g. ``кількість``,
    # ``назва``). To maintain compatibility without duplicating the model, we
    # expose a set of properties that proxy these Ukrainian names to the
    # underlying English attributes. When a direct mapping does not exist
    # (e.g. reserved quantity), we return a sensible default.

    # --- Article / Артикул ---
    @property
    def артикул(self) -> str:
        return self.article

    @артикул.setter
    def артикул(self, value: str) -> None:
        self.article = value

    # --- Name / Назва ---
    @property
    def назва(self) -> str:
        return self.name

    @назва.setter
    def назва(self, value: str) -> None:
        self.name = value

    # --- Department / Відділ ---
    @property
    def відділ(self) -> str:
        return self.dept_id

    @відділ.setter
    def відділ(self, value: str) -> None:
        self.dept_id = value

    # --- Group / Група ---
    # Зберігаємо назву групи у колонці `group_name`. Якщо колонки немає у
    # базі, SQLAlchemy створить її при ініціалізації схеми. Це дозволяє
    # заповнювати та зчитувати групу для кожного товару.
    group_name = Column("group_name", String(100), nullable=True)

    @property
    def група(self) -> str:
        """Повертає назву групи або порожній рядок, якщо група не задана."""
        return self.group_name or ""

    @група.setter
    def група(self, value: str) -> None:
        """Зберігає назву групи у полі `group_name`. Якщо передано None — ставимо None."""
        self.group_name = value if value is not None else None

    # --- Quantity / Кількість ---
    @property
    def кількість(self) -> str:
        # Convert the float quantity to a string, preserving decimals. This
        # mirrors the behaviour of the Ukrainian model, where quantities are
        # stored as strings in the database.
        return str(self.qty)

    @кількість.setter
    def кількість(self, value: Any) -> None:
        try:
            self.qty = float(str(value).replace(",", "."))
        except (ValueError, TypeError):
            # If parsing fails, reset quantity to 0.0 as a safe fallback.
            self.qty = 0.0

    # --- Reserved / Відкладено ---
    @property
    def відкладено(self) -> float:
        # There is no reserved quantity field in the English model. We return
        # zero by default; callers that rely on reserved quantities should
        # compute it via other tables (e.g. picklists) if needed.
        return 0.0

    @відкладено.setter
    def відкладено(self, value: Any) -> None:
        # The English model has no place to store reserved quantities. Ignore
        # attempts to set a value.
        pass

    # --- Months without movement / Місяці без руху ---
    @property
    def місяці_без_руху(self) -> float:
        return self.months_no_move

    @місяці_без_руху.setter
    def місяці_без_руху(self, value: Any) -> None:
        try:
            self.months_no_move = float(value)
        except (ValueError, TypeError):
            self.months_no_move = 0.0

    # --- Price / Ціна ---
    @property
    def ціна(self) -> float:
        return self.price

    @ціна.setter
    def ціна(self, value: Any) -> None:
        try:
            self.price = float(value)
        except (ValueError, TypeError):
            self.price = 0.0

    # --- Stock sum / Сума залишку ---
    @property
    def сума_залишку(self) -> Optional[float]:
        # Compute the approximate stock sum as quantity multiplied by price.
        try:
            return float(self.qty) * float(self.price)
        except (ValueError, TypeError):
            return None

    @сума_залишку.setter
    def сума_залишку(self, value: Any) -> None:
        # The English model does not store the stock sum separately. Ignore
        # attempts to assign to this property.
        pass

    # --- Active status / Активний ---
    @property
    def активний(self) -> bool:
        return bool(self.active)

    @активний.setter
    def активний(self, value: Any) -> None:
        self.active = bool(value)

    # -------------------------------------------------------------------------


class ProductCardCache(Base):
    """
    L2‑кеш для карток товару.

    - card_json: мінімально достатній JSON для швидкого рендеру картки
    - file_id: останній валідний Telegram file_id фото (якщо є)
    """

    __tablename__ = "product_card_cache"

    id = Column(Integer, primary_key=True)
    dept_id = Column(String(32), nullable=False)
    article = Column(String(32), nullable=False)

    card_json = Column(JSON, nullable=False, default=dict)  # зберігаємо словник
    file_id = Column(String(256), nullable=True)

    updated_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        UniqueConstraint("dept_id", "article", name="uq_cardcache_dept_article"),
        Index("ix_cardcache_dept_article", "dept_id", "article"),
    )


class ProductPhoto(Base):
    """
    Фото товарів з модерацією.

    - image_hash: короткий хеш для видалення дублікатів
    - order_no: для сортування (1..3)
    """

    __tablename__ = "product_photos"

    id = Column(Integer, primary_key=True)
    dept_id = Column(String(32), nullable=False)
    article = Column(String(32), nullable=False)

    file_id = Column(String(256), nullable=False)
    image_hash = Column(String(64), nullable=False)

    status = Column(String(16), nullable=False, default=PhotoStatus.PENDING.value)
    order_no = Column(Integer, nullable=False, default=1)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("ix_photos_dept_article", "dept_id", "article"),
        UniqueConstraint("dept_id", "article", "image_hash", name="uq_photos_dedupe"),
        CheckConstraint("order_no >= 1 AND order_no <= 3", name="ck_photos_order_range"),
    )


class PicklistItem(Base):
    """
    Основний список користувача (алокація з БД).

    - qty_alloc: скільки зарезервовано з БД для цього користувача
    - price_at_moment: ціна за одиницю на момент додавання
    """

    __tablename__ = "picklist_items"

    id = Column(Integer, primary_key=True)

    user_id = Column(String(64), nullable=False)
    dept_id = Column(String(32), nullable=False)
    article = Column(String(32), nullable=False)

    qty_alloc = Column(Float, nullable=False, default=0.0)
    price_at_moment = Column(Float, nullable=True)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("ix_pick_alloc_user", "user_id"),
        Index("ix_pick_alloc_dept_article", "dept_id", "article"),
        Index("ix_pick_alloc_user_dept", "user_id", "dept_id"),
        CheckConstraint("qty_alloc >= 0", name="ck_pick_alloc_nonneg"),
        # Можна зробити унікальність на (user_id, dept_id, article), щоб не плодити рядки
        UniqueConstraint(
            "user_id", "dept_id", "article", name="uq_pick_alloc_user_dept_article"
        ),
    )


class PicklistOverflowItem(Base):
    """
    Паралельний список «надлишків» користувача.

    - qty_overflow: що було запрошено понад доступне в БД
    - «надлишки» НЕ змінюють products.qty
    """

    __tablename__ = "picklist_overflow_items"

    id = Column(Integer, primary_key=True)

    user_id = Column(String(64), nullable=False)
    dept_id = Column(String(32), nullable=False)
    article = Column(String(32), nullable=False)

    qty_overflow = Column(Float, nullable=False, default=0.0)
    price_at_moment = Column(Float, nullable=True)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("ix_pick_over_user", "user_id"),
        Index("ix_pick_over_dept_article", "dept_id", "article"),
        Index("ix_pick_over_user_dept", "user_id", "dept_id"),
        CheckConstraint("qty_overflow >= 0", name="ck_pick_over_nonneg"),
        UniqueConstraint(
            "user_id", "dept_id", "article", name="uq_pick_over_user_dept_article"
        ),
    )


# --------------------------- Автооновлення timestamp -------------------------

def _touch_updated(mapper, connection, target) -> None:
    """Оновлює поле updated_at при будь‑якому апдейті/інсерті."""
    if hasattr(target, "updated_at"):
        connection.execute(
            target.__table__.update()
            .where(target.__table__.c.id == target.id)
            .values(updated_at=func.now())
        )


for cls in (Product, ProductCardCache, ProductPhoto, PicklistItem, PicklistOverflowItem):
    event.listen(cls, "after_insert", _touch_updated)
    event.listen(cls, "after_update", _touch_updated)


# ------------------------------ Утилітарне -----------------------------------

def ensure_schema(engine) -> None:
    """
    Створити таблиці, якщо їх немає. Викликати на старті застосунку.

    Для сумісності з усіма моделями проєкту викликає ``create_all`` на
    метаданих базових класів із ``database.models`` (які містять ``User`` та
    інші таблиці), а потім на метаданих локального Base. Порядок виклику не
    має значення, оскільки ``create_all`` є ідемпотентним.

    Приклад:
        from sqlalchemy import create_engine
        engine = create_engine(DB_URL, echo=False, future=True)
        ensure_schema(engine)
    """
    # Спочатку створюємо таблиці, визначені у database.models.Base (наприклад, users)
    ModelsBase.metadata.create_all(bind=engine)
    # Потім створюємо таблиці, визначені у цьому модулі
    Base.metadata.create_all(bind=engine)


# ------------------------------ ORM‑функції -----------------------------------

async def orm_find_products(
    search_query: str,
    dept_id: Optional[str] = None,
    limit: int = 30,
) -> List[Product]:
    """
    Виконує пошук товарів за артикулом або назвою.

    Повертає список товарів, де ``article`` або ``name`` містять рядок
    ``search_query``. Якщо вказано ``dept_id``, пошук обмежується заданим
    підрозділом. Нечіткий пошук може бути реалізований у майбутньому.

    :param search_query: Рядок для пошуку (артикул або частина назви).
    :param dept_id: (необов'язково) ідентифікатор підрозділу.
    :param limit: Максимальна кількість результатів.
    :return: Список об'єктів ``Product``.
    """
    # Формуємо фільтр: порівнюємо article та name незалежно від регістру
    pattern = f"%{search_query}%"
    async with async_session() as session:
        # Шукаємо у таблиці products за англомовними полями article та name.
        stmt = select(Product).where(
            or_(Product.article.ilike(pattern), Product.name.ilike(pattern))
        )
        if dept_id:
            stmt = stmt.where(Product.dept_id == dept_id)
        stmt = stmt.order_by(Product.name.asc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().unique())


async def orm_get_product_by_id(
    product_id: int,
    *,
    session: Optional[AsyncSession] = None,
    for_update: bool = False,
) -> Optional[Product]:
    """
    Повертає товар за його ID.

    Якщо ``for_update=True``, рядок блокується для оновлення (SELECT ... FOR UPDATE).
    Можна передати вже відкриту сесію для оптимізації; якщо ні — буде створена нова.

    :param product_id: ID товару.
    :param session: асинхронна сесія SQLAlchemy.
    :param for_update: чи потрібно блокувати рядок.
    :return: Об'єкт ``Product`` або ``None``, якщо не знайдено.
    """
    need_own_session = session is None
    async_session_to_use = session or async_session()
    # Повертаємо товар, запитуючи англомовну таблицю products. Запити до
    # української моделі не працюють, оскільки в таблиці products немає
    # відповідних стовпців (наприклад, "артикул"). Властивості, визначені
    # у класі ``Product`` нижче, надають доступ до українських полів.
    if need_own_session:
        async with async_session_to_use as local_session:
            stmt = select(Product).where(Product.id == product_id)
            if for_update:
                stmt = stmt.with_for_update()
            res = await local_session.execute(stmt)
            return res.scalar_one_or_none()
    else:
        stmt = select(Product).where(Product.id == product_id)
        if for_update:
            stmt = stmt.with_for_update()
        res = await session.execute(stmt)
        return res.scalar_one_or_none()


def orm_get_all_products_sync() -> List[Product]:
    """
    Повертає всі товари у синхронному режимі.

    Використовується у задачах та скриптах, які не є асинхронними.
    """
    with sync_session() as session:
        return session.query(Product).all()


async def orm_smart_import(*args: Any, **kwargs: Any) -> None:
    """
    Плейсхолдер для імпорту даних із файлів Excel.

    Майбутня реалізація має здійснювати валідацію даних, оновлення
    залишків та логування змін. Поки що функція піднімає
    ``NotImplementedError``, щоб повідомити про необхідність реалізації.
    """
    raise NotImplementedError("orm_smart_import is not implemented yet")


async def orm_subtract_collected(*args: Any, **kwargs: Any) -> None:
    """
    Плейсхолдер для зменшення залишків після формування списку.

    У майбутньому ця функція повинна списувати зарезервовані кількості
    з таблиці ``products``, вести облік виконаних операцій та
    забезпечувати транзакційну цілісність. Наразі вона не реалізована.
    """
    raise NotImplementedError("orm_subtract_collected is not implemented yet")


def _extract_article(text: str | None) -> Optional[str]:
    """
    Допоміжна функція для виділення артикула (8 цифр) з вхідного тексту.

    Використовує регулярний вираз для пошуку на початку рядка. Якщо
    артикул не знайдено, повертає ``None``.

    :param text: Текст, що може містити артикул.
    :return: Рядок з 8 цифрами або ``None``.
    """
    if not text:
        return None
    m = re.match(r"^\s*(\d{8})\b", text)
    return m.group(1) if m else None