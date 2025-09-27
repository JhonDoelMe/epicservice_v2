# -*- coding: utf-8 -*-
"""
SQLAlchemy-моделі для ERP-бота.

Таблиці:
- products                  — довідник/залишки товарів (істина з БД)
- product_card_cache        — L2-кеш карток (JSON + file_id), інвалідується після змін
- product_photos            — фото товарів (до 3 шт/артикул, з модерацією)
- picklist_items            — «алокація» користувача (те, що списано з БД у список)
- picklist_overflow_items   — «надлишки» користувача (поза БД, лише у паралельному списку)

Примітки:
- Унікальність товару — за (dept_id, article).
- «Надлишки» НЕ впливають на таблицю products.
- Часові поля onupdate через події SQLAlchemy.
"""

from __future__ import annotations

import enum
import json
from datetime import datetime
from typing import Any, Optional

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
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import declarative_base

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


class ProductCardCache(Base):
    """
    L2-кеш для карток товару.

    - card_json: мінімально достатній JSON для швидкого рендеру картки
    - file_id: останній валідний Telegram file_id фото (якщо є)
    """
    __tablename__ = "product_card_cache"

    id = Column(Integer, primary_key=True)
    dept_id = Column(String(32), nullable=False)
    article = Column(String(32), nullable=False)

    card_json = Column(JSON, nullable=False, default=dict)   # зберігаємо словник
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
        UniqueConstraint("user_id", "dept_id", "article", name="uq_pick_alloc_user_dept_article"),
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
        UniqueConstraint("user_id", "dept_id", "article", name="uq_pick_over_user_dept_article"),
    )


# --------------------------- Автооновлення timestamp -------------------------

def _touch_updated(mapper, connection, target):
    """Оновлює поле updated_at при будь-якому апдейті/інсерті."""
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
    Приклад:
        from sqlalchemy import create_engine
        engine = create_engine(DB_URL, echo=False, future=True)
        ensure_schema(engine)
    """
    Base.metadata.create_all(bind=engine)
