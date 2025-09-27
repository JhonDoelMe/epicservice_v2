# epicservice/database/models.py

from typing import List

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Integer,
                        String, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Базовий клас для декларативних моделей SQLAlchemy."""
    pass


class User(Base):
    """Модель, що представляє користувача бота."""
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=func.now())

    saved_lists: Mapped[List["SavedList"]] = relationship(back_populates="user")
    temp_list_items: Mapped[List["TempList"]] = relationship(back_populates="user")


class Product(Base):
    """Модель, що представляє товар на складі."""
    __tablename__ = 'products'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    артикул: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    назва: Mapped[str] = mapped_column(String(255))
    відділ: Mapped[int] = mapped_column(BigInteger)
    група: Mapped[str] = mapped_column(String(100))
    кількість: Mapped[str] = mapped_column(String(50))
    відкладено: Mapped[int] = mapped_column(Integer, default=0)
    
    # --- ОНОВЛЕНІ ТА НОВІ ПОЛЯ (УКРАЇНСЬКОЮ) ---
    # "м" - місяців без руху
    місяці_без_руху: Mapped[int] = mapped_column(Integer, nullable=True, default=0)
    # "с" - сума залишку
    сума_залишку: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)
    # "ц" - ціна за одиницю
    ціна: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)
    # Статус активності товару
    активний: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class SavedList(Base):
    """Модель, що представляє збережений список товарів користувача."""
    __tablename__ = 'saved_lists'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    file_name: Mapped[str] = mapped_column(String(100))
    file_path: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=func.now())

    items: Mapped[List["SavedListItem"]] = relationship(back_populates="saved_list", cascade="all, delete-orphan")
    user: Mapped["User"] = relationship(back_populates="saved_lists")


class SavedListItem(Base):
    """Модель, що представляє один пункт у збереженому списку."""
    __tablename__ = 'saved_list_items'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(ForeignKey('saved_lists.id'))
    article_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer)

    saved_list: Mapped["SavedList"] = relationship(back_populates="items")


class TempList(Base):
    """Модель, що представляє тимчасовий (поточний) список товарів користувача."""
    __tablename__ = 'temp_lists'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    quantity: Mapped[int] = mapped_column(Integer)

    product: Mapped["Product"] = relationship()
    user: Mapped["User"] = relationship(back_populates="temp_list_items")