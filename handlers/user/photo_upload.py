# -*- coding: utf-8 -*-
"""
Завантаження фото товарів від користувачів (aiogram 3.x).

Сценарій:
- Користувач надсилає фото з підписом "dept:article", напр. "100:12345678".
- Бот:
    1) Витягує найбільше фото з повідомлення.
    2) Завантажує байти, оптимізує (JPEG 1280/512).
    3) Рахує геші (aHash + sha256) і робить дедуплікацію.
    4) Зберігає оптимізовані файли у локальне сховище (utils.storage).
    5) Пише запис у ProductPhoto зі status="pending".
- Відповідь: підтвердження про надсилання на модерацію.

Примітки:
- Щоб уникнути прив'язки до FSM, використовуємо простий формат у підписі. Це надійно і прозоро.
- Після модерації адмін-хендлер оновить статус і, за потреби, інвалідить кеш картки.

Залежності:
    aiogram 3.x
    utils.image_opt.optimize_for_telegram
    utils.storage.save_bytes
    database.orm.products.ProductPhoto
"""

from __future__ import annotations

import io
import re
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ContentType

from database.session import get_session  # type: ignore
from database.orm.products import ProductPhoto  # type: ignore
from utils.image_opt import optimize_for_telegram
from utils.storage import save_bytes

router = Router(name="photo_upload")

CAPTION_RE = re.compile(r"^\s*(?P<dept>[A-Za-z0-9_\-\.]+)\s*:\s*(?P<art>[A-Za-z0-9_\-\.]+)\s*$")


def _pick_largest_photo(msg: Message):
    """
    Вибрати найбільший варіант фото з message.photo.
    """
    if not msg.photo:
        return None
    return max(msg.photo, key=lambda p: (p.width or 0) * (p.height or 0))


async def _download_bytes(msg: Message) -> Optional[bytes]:
    """
    Завантажити байти найбільшого фото з повідомлення.
    aiogram 3.x: Bot.download(file, destination).
    """
    ph = _pick_largest_photo(msg)
    if not ph:
        return None
    buf = io.BytesIO()
    # універсальний спосіб: aiogram 3.x має generic download
    await msg.bot.download(ph, buf)
    return buf.getvalue()


@router.message(Command("addphoto"))
async def addphoto_help(message: Message):
    """
    Підказка по формату. Команда необов'язкова, просто показує інструкцію.
    """
    await message.answer(
        "Щоб додати фото товару, надішліть <b>фото</b> з підписом у форматі:\n"
        "<code>відділ:артикул</code>\n\n"
        "Наприклад:\n<code>100:12345678</code>\n\n"
        "Фото буде передано на модерацію.",
        parse_mode="HTML"
    )


@router.message(content_types=ContentType.PHOTO)
async def handle_photo_upload(message: Message):
    """
    Основний обробник: приймає фото, читає підпис, зберігає, створює запис у БД.
    """
    caption = (message.caption or "").strip()
    m = CAPTION_RE.match(caption)
    if not m:
        await message.reply(
            "Не впізнав підпис. Використайте формат <code>відділ:артикул</code>, напр. <code>100:12345678</code>.",
            parse_mode="HTML"
        )
        return

    dept_id = m.group("dept")
    article = m.group("art")

    # 1) Завантажити байти
    try:
        raw_bytes = await _download_bytes(message)
        if not raw_bytes:
            await message.reply("Не вдалося завантажити фото. Спробуйте ще раз.")
            return
    except Exception:
        await message.reply("Сталася помилка під час завантаження фото. Спробуйте ще раз.")
        return

    # 2) Оптимізувати
    try:
        opt = optimize_for_telegram(raw_bytes)
        main_bytes = opt["bytes_main"]
        thumb_bytes = opt["bytes_thumb"]
        ahash = opt["ahash"]
        sha_main = opt["sha256_main"]
    except Exception:
        await message.reply("Не вдалося обробити фото. Перевірте файл і спробуйте ще раз.")
        return

    # 3) Дедуплікація: перевіримо image_hash (aHash) у БД
    with get_session() as s:
        exists = s.query(ProductPhoto).filter(
            ProductPhoto.dept_id == str(dept_id),
            ProductPhoto.article == str(article),
            ProductPhoto.image_hash == str(ahash)
        ).one_or_none()
        if exists:
            await message.reply("Таке фото вже було надіслане раніше. Дякуємо.")
            return

        # 4) Збереження файлів у локальне сховище (не обов'язково тримати шлях у БД)
        stored_main = save_bytes(
            main_bytes,
            category="photos",
            dept_id=str(dept_id),
            article=str(article),
            ext_hint="jpg",
            prefix="main"
        )
        stored_thumb = save_bytes(
            thumb_bytes,
            category="photos",
            dept_id=str(dept_id),
            article=str(article),
            ext_hint="jpg",
            prefix="thumb"
        )

        # 5) Запис у БД: статус pending, file_id беремо з Telegram-фото користувача
        #     Беремо file_id найбільшого фото (працює стабільно для повторних відправлень Telegram)
        largest = _pick_largest_photo(message)
        file_id = largest.file_id if largest else None

        photo = ProductPhoto(
            dept_id=str(dept_id),
            article=str(article),
            file_id=file_id,
            image_hash=str(ahash),
            status="pending",
            order_no=1,  # адмін зможе поміняти порядок
        )
        s.add(photo)
        s.commit()

    # 6) Фінальна відповідь
    await message.reply(
        "Фото отримано ✅\n"
        "Воно відправлене на модерацію. Після підтвердження з'явиться в картці товару.",
    )
