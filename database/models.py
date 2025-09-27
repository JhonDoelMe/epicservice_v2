"""
Моделі SQLAlchemy для таблиць бази даних.

Цей модуль містить класи, що відображають користувачів, тимчасові та
збережені списки, а також товари. Для сумісності з існуючими частинами
проєкту поля моделі ``Product`` мають українські назви, але
відображаються на англомовні стовпці у таблиці ``products``.

Клас ``Product`` у цій версії не зберігає поля «група», «відкладено» та
«сума_залишку» у базі даних, оскільки відповідні колонки відсутні. Вони
реалізовані як властивості, що повертають значення за замовчуванням або
обчислюються на льоту.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Базовий клас для декларативних моделей SQLAlchemy."""
    pass


class User(Base):
    """Модель, що представляє користувача бота."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=func.now())

    saved_lists: Mapped[List["SavedList"]] = relationship(back_populates="user")
    temp_list_items: Mapped[List["TempList"]] = relationship(back_populates="user")


class Product(Base):
    """
    Модель, що представляє товар на складі.

    Атрибути цієї моделі мають українські назви, але фізично
    зберігаються у колонках з англомовними іменами. Це дозволяє
    використовувати зручні для користувача назви полів без порушення
    відповідності схемі бази даних, у якій стовпці мають імена
    ``article``, ``name``, ``dept_id``, ``qty``, ``months_no_move``,
    ``price`` та ``active``.

    Поля ``група``, ``відкладено`` та ``сума_залишку`` не мають
    відповідних стовпців у таблиці ``products``. Вони реалізовані як
    властивості з розумними значеннями за замовчуванням.
    """

    __tablename__ = "products"

    # Первинний ключ
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Артикул (колонка 'article')
    артикул: Mapped[str] = mapped_column(
        "article", String(20), unique=True, index=True
    )

    # Назва (колонка 'name')
    назва: Mapped[str] = mapped_column("name", String(255))

    # Відділ (колонка 'dept_id')
    відділ: Mapped[int] = mapped_column("dept_id", BigInteger)

    # Кількість (колонка 'qty')
    кількість: Mapped[str] = mapped_column("qty", String(50))

    # Група (колонка 'group_name')

    # Місяці без руху (колонка 'months_no_move')
    місяці_без_руху: Mapped[int] = mapped_column(
        "months_no_move", Integer, nullable=True, default=0
    )

    # Ціна за одиницю (колонка 'price')
    ціна: Mapped[float] = mapped_column(
        "price", Float, nullable=True, default=0.0
    )

    # Статус активності (колонка 'active')
    активний: Mapped[bool] = mapped_column(
        "active", Boolean, default=True, index=True
    )

    # ------------------------------------------------------------------
    # Поля, що не зберігаються у таблиці, або мають альтернативні назви,
    # але потрібні для сумісності

    @property
    def група(self) -> str:
        """
        Таблиця ``products`` не містить колонки для групи. Це поле
        повертає порожній рядок для сумісності з інтерфейсом.
        """
        return ""

    @група.setter
    def група(self, value: str) -> None:
        """Пропускає встановлення назви групи, оскільки вона не зберігається."""
        pass

    @property
    def відкладено(self) -> int:
        """Повертає нуль, оскільки відкладена кількість не зберігається."""
        return 0

    @відкладено.setter
    def відкладено(self, value: Any) -> None:
        """Ігнорує встановлення відкладеної кількості."""
        pass

    @property
    def сума_залишку(self) -> float:
        """Обчислює суму залишку як кількість, помножену на ціну."""
        try:
            return float(str(self.кількість).replace(",", ".")) * float(self.ціна)
        except (ValueError, TypeError):
            return 0.0

    @сума_залишку.setter
    def сума_залишку(self, value: Any) -> None:
        """Ігнорує встановлення суми залишку, бо вона не зберігається окремо."""
        pass


class SavedList(Base):
    """Модель, що представляє збережений список товарів користувача."""

    __tablename__ = "saved_lists"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(100))
    file_path: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=func.now())

    items: Mapped[List["SavedListItem"]] = relationship(back_populates="saved_list", cascade="all, delete-orphan")
    user: Mapped["User"] = relationship(back_populates="saved_lists")


class SavedListItem(Base):
    """Модель, що представляє один пункт у збереженому списку."""

    __tablename__ = "saved_list_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("saved_lists.id"))
    article_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer)

    saved_list: Mapped["SavedList"] = relationship(back_populates="items")


class TempList(Base):
    """Модель, що представляє тимчасовий (поточний) список товарів користувача."""

    __tablename__ = "temp_lists"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)

    # Зв'язок із товаром та користувачем
    product: Mapped["Product"] = relationship()
    user: Mapped["User"] = relationship(back_populates="temp_list_items")
