# -*- coding: utf-8 -*-
"""
Рендерери UI-пейлоадів (без Telegram-залежностей).

render_product_card(session, dept_id, article) -> (card_json: dict, file_id: Optional[str])
"""

from __future__ import annotations
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from database.orm.products import Product, ProductPhoto  # type: ignore

def _pick_approved_photo(session: Session, dept_id: str, article: str) -> Optional[str]:
    """
    Взяти file_id першого схваленого фото, якщо є. Повертає None, якщо немає.
    """
    # Якщо у тебе інший спосіб вибору — підправ нижче.
    q = session.query(ProductPhoto).filter(
        ProductPhoto.dept_id == str(dept_id),
        ProductPhoto.article == str(article),
        ProductPhoto.status == "approved"
    ).order_by(ProductPhoto.order_no.asc())
    row = q.first()
    return row.file_id if row else None

def render_product_card(session: Session, dept_id: str, article: str) -> Tuple[dict, Optional[str]]:
    """
    Зібрати payload картки товару. Не стосується Telegram безпосередньо.
    Повертає card_json і, за наявності, file_id фото для відправки.
    """
    p = session.query(Product).filter(
        Product.dept_id == str(dept_id),
        Product.article == str(article)
    ).one_or_none()

    if not p:
        # Мінімальний payload на випадок відсутності
        return ({
            "dept_id": str(dept_id),
            "article": str(article),
            "title": "Товар не знайдено",
            "subtitle": "",
            "available": 0.0,
            "price": 0.0,
            "can_add": False,
            "note": "Цей артикул відсутній у довіднику."
        }, None)

    title = f"{p.article} • {p.name}".strip()
    subtitle = f"Відділ {p.dept_id}"
    available = float(p.qty or 0.0)
    price = float(p.price or 0.0)

    card_json = {
        "dept_id": str(p.dept_id),
        "article": str(p.article),
        "title": title,
        "subtitle": subtitle,
        "available": available,
        "price": price,
        "can_add": bool(available > 0.0),
        "note": None
    }

    # Фото: беремо схвалене або None
    file_id = _pick_approved_photo(session, str(p.dept_id), str(p.article))
    return card_json, file_id
