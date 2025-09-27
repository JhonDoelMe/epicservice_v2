# -*- coding: utf-8 -*-
"""
Локальне сховище файлів (зображення, архіви, експорти).

Можливості:
- Збереження байтів у стабільній структурі каталогів з датою та елементами сутності (dept_id, article, user_id).
- Повернення метаданих (шлях, розмір, sha256).
- Завантаження/видалення файлів.
- Підчищення старих файлів за ретеншн-періодом.

Налаштування через .env:
    MEDIA_ROOT=media
    MEDIA_RETENTION_DAYS=90

Рекомендації:
- Для зображень перед збереженням використовуй utils.image_opt.optimize_*.
- Для публічної роздачі (якщо знадобиться) тримай MEDIA_ROOT за reverse-proxy.

ПРИМІТКА: модуль синхронний. Всередині aiogram 3.x викликай у thread-пулі, якщо обсяги великі.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(override=True)

MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "media")).resolve()
MEDIA_RETENTION_DAYS = int(os.getenv("MEDIA_RETENTION_DAYS", "90") or 0)

# Створимо корінь сховища, якщо його немає
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)


# ------------------------------- Утиліти --------------------------------------

def _now_str() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_segment(s: str) -> str:
    """
    Безпечний сегмент шляху: тільки букви/цифри/дефіс/підкреслення.
    Пробіли → підкреслення, решту відкидаємо.
    """
    import re
    s = (s or "").strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^A-Za-z0-9_\-\.]+", "", s)
    return s or "x"


def _ext_for(mime_or_hint: Optional[str], default_ext: str = "bin") -> str:
    """
    Вгадати розширення. Якщо hint має вигляд 'image/jpeg' або '.jpg' — повернемо доречне.
    """
    hint = (mime_or_hint or "").lower().strip()
    if not hint:
        return default_ext
    if hint.startswith("."):
        return hint.lstrip(".")
    # грубий мапінг популярних MIME
    if hint in ("image/jpeg", "image/jpg"):
        return "jpg"
    if hint in ("image/webp",):
        return "webp"
    if hint in ("image/png",):
        return "png"
    if hint in ("application/zip", "application/x-zip-compressed"):
        return "zip"
    if hint in ("text/csv", "application/csv"):
        return "csv"
    if hint in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",):
        return "xlsx"
    if hint in ("application/vnd.oasis.opendocument.spreadsheet",):
        return "ods"
    return default_ext


# ------------------------------- Дані-відповідь -------------------------------

@dataclass
class StoredFile:
    """
    Результат збереження файлу.
    """
    path: Path
    rel_path: Path
    size: int
    sha256: str

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "rel_path": str(self.rel_path),
            "size": self.size,
            "sha256": self.sha256,
        }


# --------------------------------- API ----------------------------------------

def ensure_subdir(*parts: str) -> Path:
    """
    Забезпечити існування підкаталогу в MEDIA_ROOT і повернути повний шлях.
    parts — безпечні сегменти (будуть очищені).
    """
    safe_parts = [_safe_segment(p) for p in parts if p is not None]
    p = MEDIA_ROOT.joinpath(*safe_parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_bytes(
    data: bytes,
    *,
    category: str = "misc",
    dept_id: Optional[str] = None,
    article: Optional[str] = None,
    user_id: Optional[str] = None,
    ext_hint: Optional[str] = None,
    prefix: Optional[str] = None,
) -> StoredFile:
    """
    Зберегти масив байтів у файлову систему.

    Структура директорій:
        MEDIA_ROOT/<category>/<YYYY>/<MM>/<dept_or_user>/<article?>/

    Ім'я файлу:
        <prefix_or_file>_<timestamp>_<sha8>.<ext>

    Повертає StoredFile з абсолютним шляхом та відносним.

    ПРИКЛАД:
        save_bytes(img_bytes, category="photos", dept_id="100", article="12345678", ext_hint="jpg")
    """
    year = dt.datetime.now().strftime("%Y")
    month = dt.datetime.now().strftime("%m")

    # Базовий сегмент: відділ або користувач або 'common'
    base_seg = _safe_segment(dept_id or user_id or "common")
    subdir_parts = [category, year, month, base_seg]
    if article:
        subdir_parts.append(_safe_segment(article))
    folder = ensure_subdir(*subdir_parts)

    sha = _sha256(data)
    ext = _ext_for(ext_hint, default_ext="bin")
    ts = _now_str()
    name_prefix = _safe_segment(prefix or category or "file")

    filename = f"{name_prefix}_{ts}_{sha[:8]}.{ext}"
    full_path = folder / filename

    with open(full_path, "wb") as f:
        f.write(data)

    rel_path = full_path.relative_to(MEDIA_ROOT)
    return StoredFile(path=full_path, rel_path=rel_path, size=full_path.stat().st_size, sha256=sha)


def read_bytes(rel_path: str | Path) -> bytes:
    """
    Прочитати файл за відносним шляхом від MEDIA_ROOT.
    """
    p = MEDIA_ROOT / Path(rel_path)
    with open(p, "rb") as f:
        return f.read()


def delete_file(rel_path: str | Path) -> bool:
    """
    Видалити файл за відносним шляхом. Повертає True, якщо видалено.
    """
    p = MEDIA_ROOT / Path(rel_path)
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def cleanup_old(category: Optional[str] = None, retention_days: int = MEDIA_RETENTION_DAYS) -> int:
    """
    Підчистити файли старше retention_days. Повертає кількість видалених файлів.
    Якщо category задано — чистимо тільки в цій категорії.
    """
    if retention_days <= 0:
        return 0

    base = MEDIA_ROOT / _safe_segment(category) if category else MEDIA_ROOT
    if not base.exists():
        return 0

    now = dt.datetime.now()
    removed = 0

    for p in base.rglob("*"):
        try:
            if not p.is_file():
                continue
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime)
            if (now - mtime).days > retention_days:
                p.unlink(missing_ok=True)
                removed += 1
        except Exception:
            continue

    return removed
