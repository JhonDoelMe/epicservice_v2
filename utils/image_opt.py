# -*- coding: utf-8 -*-
"""
Оптимізація зображень для карток товарів.

Мета:
- Приймати фото з Telegram/файлів (bytes) і повертати нормалізовані JPEG/WEBP.
- Виправляти EXIF-орієнтацію, очищати метадані.
- Робити стиснення, ресайз до ліміту по довшій стороні.
- Генерувати прев'ю (thumbnail).
- Обчислювати стабільний геш для дедуплікації (aHash + SHA256).

Залежності:
    Pillow (PIL)

Публічні функції:
    load_image(bytes_data) -> PIL.Image.Image
    optimize_image(bytes_data, *, max_side=1280, thumb_side=512, quality=85, fmt="JPEG") -> dict
    compute_ahash(img: PIL.Image.Image, hash_size=8) -> str
    compute_sha256(data: bytes) -> str
"""

from __future__ import annotations

import io
import hashlib
from typing import Dict, Tuple

from PIL import Image, ImageOps


# ------------------------------ Базові утиліти --------------------------------

def load_image(bytes_data: bytes) -> Image.Image:
    """
    Відкрити зображення з bytes у режимі "RGB" без метаданих і з поправкою EXIF-орієнтації.
    """
    im = Image.open(io.BytesIO(bytes_data))
    # Вирівняти орієнтацію за EXIF, якщо є
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass

    # Перевести у RGB (щоб уникати проблем з "P", "LA", "RGBA")
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    elif im.mode == "L":
        im = im.convert("RGB")

    return im


def _strip_metadata(img: Image.Image) -> Image.Image:
    """
    Повернути копію без метаданих (EXIF, ICC).
    """
    out = Image.new(img.mode, img.size)
    out.putdata(list(img.getdata()))
    return out


def _resize_max_side(img: Image.Image, max_side: int) -> Image.Image:
    """
    Пропорційно зменшити зображення так, щоб найбільша сторона була <= max_side.
    Якщо вже менше — не змінюємо.
    """
    w, h = img.size
    side = max(w, h)
    if side <= max_side:
        return img
    scale = max_side / float(side)
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return img.resize(new_size, Image.LANCZOS)


def _save_bytes(img: Image.Image, *, fmt: str = "JPEG", quality: int = 85, optimize: bool = True) -> bytes:
    """
    Зберегти у bytes із заданим форматом.
    Для JPEG: вмикаємо subsampling=1 (chroma subsampling), progressive.
    Для WEBP: quality впливає на розмір, lossless=False.
    """
    buf = io.BytesIO()
    fmt_u = fmt.upper()
    if fmt_u == "JPEG":
        img.save(buf, format="JPEG", quality=max(1, min(quality, 95)), optimize=optimize, progressive=True, subsampling="4:2:0")
    elif fmt_u == "WEBP":
        img.save(buf, format="WEBP", quality=max(1, min(quality, 95)), method=6)
    else:
        img.save(buf, format=fmt_u)
    return buf.getvalue()


# ------------------------------ Геші ------------------------------------------

def compute_ahash(img: Image.Image, hash_size: int = 8) -> str:
    """
    Perceptual average-hash (aHash), повертає hex-рядок довжини hash_size*hash_size/4.
    """
    # Градації сірого, зменшення
    small = img.convert("L").resize((hash_size, hash_size), Image.LANCZOS)
    # Середнє значення яскравості
    pixels = list(small.getdata())
    avg = sum(pixels) / float(len(pixels)) if pixels else 0
    bits = ["1" if p >= avg else "0" for p in pixels]
    # Пакуємо по 4 біти в hex
    out = []
    for i in range(0, len(bits), 4):
        nibble = bits[i:i + 4]
        out.append(f"{int(''.join(nibble), 2):x}")
    return "".join(out)


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------ Головне API -----------------------------------

def optimize_image(
    bytes_data: bytes,
    *,
    max_side: int = 1280,
    thumb_side: int = 512,
    quality: int = 85,
    fmt: str = "JPEG",
) -> Dict[str, object]:
    """
    Приймає bytes оригіналу, повертає словник з оптимізованими байтами і метаданими.

    Параметри:
        max_side  — довша сторона для основного зображення
        thumb_side — довша сторона для прев'ю
        quality   — якість JPEG/WEBP (1..95)
        fmt       — "JPEG" або "WEBP" (за потреби можна інші)

    Повертає:
        {
          "format": "JPEG",
          "width": int,
          "height": int,
          "bytes_main": bytes,
          "bytes_thumb": bytes,
          "sha256_main": str,
          "sha256_thumb": str,
          "ahash": str,              # aHash від основного зображення
        }
    """
    # 1) Завантажити і нормалізувати
    img = load_image(bytes_data)
    img = _strip_metadata(img)

    # 2) Основне зображення
    main_img = _resize_max_side(img, max_side)
    main_bytes = _save_bytes(main_img, fmt=fmt, quality=quality, optimize=True)

    # 3) Прев'ю
    thumb_img = _resize_max_side(img, thumb_side)
    thumb_bytes = _save_bytes(thumb_img, fmt=fmt, quality=min(quality, 80), optimize=True)

    # 4) Геші
    ahex = compute_ahash(main_img, hash_size=8)
    sha_main = compute_sha256(main_bytes)
    sha_thumb = compute_sha256(thumb_bytes)

    w, h = main_img.size

    return {
        "format": fmt.upper(),
        "width": int(w),
        "height": int(h),
        "bytes_main": main_bytes,
        "bytes_thumb": thumb_bytes,
        "sha256_main": sha_main,
        "sha256_thumb": sha_thumb,
        "ahash": ahex,
    }


# ------------------------------ Зручні обгортки -------------------------------

def optimize_for_telegram(bytes_data: bytes) -> Dict[str, object]:
    """
    Профіль «за замовчуванням» для Telegram-карток:
      - JPEG, довша сторона 1280, прев'ю 512, якість 85/80.
    """
    return optimize_image(bytes_data, max_side=1280, thumb_side=512, quality=85, fmt="JPEG")


def optimize_light(bytes_data: bytes) -> Dict[str, object]:
    """
    Легкий профіль для списків/мініатюр:
      - JPEG, довша сторона 960, прев'ю 384, якість 80/72.
    """
    return optimize_image(bytes_data, max_side=960, thumb_side=384, quality=80, fmt="JPEG")
