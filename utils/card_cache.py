# -*- coding: utf-8 -*-
"""
L1/L2-кеш карток товарів.

Призначення:
- L1: ін-пам'яті кеш з TTL та обмеженням розміру (швидкий доступ у процесі).
- L2: таблиця product_card_cache у БД (переживає рестарти, спільна для всіх інстансів).
- API: get_card / set_card / update_file_id / invalidate / get_or_render_card.

Налаштування через .env:
    CARD_L1_TTL_SEC=300
    CARD_L1_MAX_ITEMS=5000
    CARD_L2_ENABLED=1
"""

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from dotenv import load_dotenv
from sqlalchemy import and_
from sqlalchemy.orm import Session

from database.orm.products import ProductCardCache  # type: ignore

load_dotenv(override=True)
logger = logging.getLogger(__name__)

# ------------------------------ Конфіг ----------------------------------------

CARD_L1_TTL_SEC = int(os.getenv("CARD_L1_TTL_SEC", "300") or 0)
CARD_L1_MAX_ITEMS = int(os.getenv("CARD_L1_MAX_ITEMS", "5000") or 0)
CARD_L2_ENABLED = os.getenv("CARD_L2_ENABLED", "1") in ("1", "true", "True", "yes", "YES")

# ------------------------------ L1-кеш ----------------------------------------

@dataclass
class _L1Entry:
    value: Dict[str, Any]
    file_id: Optional[str]
    ts: float  # сек від epoch


class _LRUCache:
    """
    Примітивний LRU з TTL. Без сторонніх залежностей.
    """
    def __init__(self, cap: int, ttl: int):
        self.cap = max(0, int(cap))
        self.ttl = max(0, int(ttl))
        self._data: Dict[Tuple[str, str], _L1Entry] = {}
        self._use: Dict[Tuple[str, str], float] = {}

    def _evict_if_needed(self):
        if self.cap <= 0 or len(self._data) <= self.cap:
            return
        k_old = min(self._use, key=self._use.get)
        self._data.pop(k_old, None)
        self._use.pop(k_old, None)

    def get(self, key: Tuple[str, str]) -> Optional[_L1Entry]:
        if key not in self._data:
            return None
        e = self._data[key]
        now = time.time()
        if self.ttl and now - e.ts > self.ttl:
            self._data.pop(key, None)
            self._use.pop(key, None)
            return None
        self._use[key] = now
        return e

    def set(self, key: Tuple[str, str], value: Dict[str, Any], file_id: Optional[str]) -> None:
        now = time.time()
        self._data[key] = _L1Entry(value=value, file_id=file_id, ts=now)
        self._use[key] = now
        self._evict_if_needed()

    def invalidate(self, key: Tuple[str, str]) -> None:
        self._data.pop(key, None)
        self._use.pop(key, None)

    def invalidate_many(self, keys: Iterable[Tuple[str, str]]) -> None:
        for k in keys:
            self.invalidate(k)

    def clear(self) -> None:
        self._data.clear()
        self._use.clear()


_L1 = _LRUCache(cap=CARD_L1_MAX_ITEMS, ttl=CARD_L1_TTL_SEC)

# ------------------------------ Публічний API ---------------------------------

def cache_key(dept_id: str, article: str) -> Tuple[str, str]:
    return (str(dept_id), str(article))


def get_card(session: Session, dept_id: str, article: str) -> Optional[Dict[str, Any]]:
    """
    Отримати картку: L1 → L2 → None.
    Повертає card_json і додає 'file_id', якщо є.
    """
    k = cache_key(dept_id, article)

    # L1
    e = _L1.get(k)
    if e:
        data = dict(e.value)
        if e.file_id:
            data.setdefault("file_id", e.file_id)
        return data

    # L2
    if CARD_L2_ENABLED:
        row = session.query(ProductCardCache).filter(
            and_(ProductCardCache.dept_id == k[0], ProductCardCache.article == k[1])
        ).one_or_none()
        if row:
            data = dict(row.card_json or {})
            if row.file_id:
                data.setdefault("file_id", row.file_id)
            _L1.set(k, data, row.file_id)
            return data

    return None


def set_card(session: Session, dept_id: str, article: str, card_json: Dict[str, Any], file_id: Optional[str] = None) -> None:
    """
    Зберегти картку в L1 і L2.
    """
    k = cache_key(dept_id, article)
    _L1.set(k, card_json, file_id)

    if CARD_L2_ENABLED:
        row = session.query(ProductCardCache).filter(
            and_(ProductCardCache.dept_id == k[0], ProductCardCache.article == k[1])
        ).one_or_none()
        if not row:
            row = ProductCardCache(dept_id=k[0], article=k[1])
            session.add(row)
        row.card_json = card_json
        if file_id is not None:
            row.file_id = file_id  # збережемо актуальний file_id


def update_file_id(session: Session, dept_id: str, article: str, file_id: Optional[str]) -> None:
    """
    Оновити тільки file_id у кеші.
    """
    k = cache_key(dept_id, article)
    e = _L1.get(k)
    if e:
        _L1.set(k, e.value, file_id)

    if CARD_L2_ENABLED:
        row = session.query(ProductCardCache).filter(
            and_(ProductCardCache.dept_id == k[0], ProductCardCache.article == k[1])
        ).one_or_none()
        if row:
            row.file_id = file_id


def invalidate(session: Session, dept_id: str, article: str) -> None:
    """
    Видалити запис з L1 і L2 (щоб наступне відкриття картки зрендерило свіжі дані).
    """
    k = cache_key(dept_id, article)
    _L1.invalidate(k)
    if CARD_L2_ENABLED:
        session.query(ProductCardCache).filter(
            and_(ProductCardCache.dept_id == k[0], ProductCardCache.article == k[1])
        ).delete(synchronize_session=False)


def invalidate_many(session: Session, pairs: Iterable[Tuple[str, str]]) -> None:
    keys = [cache_key(d, a) for d, a in pairs]
    _L1.invalidate_many(keys)
    if CARD_L2_ENABLED and keys:
        for d, a in keys:
            session.query(ProductCardCache).filter(
                and_(ProductCardCache.dept_id == d, ProductCardCache.article == a)
            ).delete(synchronize_session=False)


def clear_l1() -> None:
    """Очистити L1 повністю (наприклад, при релізі)."""
    _L1.clear()


# ------------------------------ Шорткат ---------------------------------------

def get_or_render_card(session: Session, dept_id: str, article: str, renderer) -> Dict[str, Any]:
    """
    Повертає картку з кешу або викликає renderer(dept_id, article) -> (card_json, file_id)
    і зберігає результат у кеш.
    """
    cached = get_card(session, dept_id, article)
    if cached is not None:
        return cached

    card_json, file_id = renderer(session, dept_id, article)
    if not isinstance(card_json, dict):
        raise ValueError("renderer має повертати (dict, file_id|None)")
    set_card(session, dept_id, article, card_json, file_id)
    return dict(card_json, **({"file_id": file_id} if file_id else {}))
