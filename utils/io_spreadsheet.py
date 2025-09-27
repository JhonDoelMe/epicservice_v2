# -*- coding: utf-8 -*-
"""
Універсальний ввід/вивід табличних файлів для бота.

Підтримка форматів:
- .xlsx / .xlsm  (через pandas + openpyxl/xlsxwriter)
- .ods           (читання/запис через pyexcel-ods3)
- .csv           (pandas)

Основні цілі:
- Один вхідний API для імпорту: read_any_spreadsheet(path) -> pandas.DataFrame
- Один вихідний API для експорту: write_any_spreadsheet(df, path, fmt=None, ...)
- Акуратна робота з числовими рядками локального формату: "12 345,67"
- Мінімум залежностей у коді (логіка ізольована тут)

Залежності (у requirements.txt):
    pandas
    openpyxl             # для .xlsx/.xlsm
    xlsxwriter           # бажаний движок запису .xlsx (швидкий)
    pyexcel-ods3         # для .ods
    odfpy                # залежність для pyexcel-ods3
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

import pandas as pd

try:
    # Ці імпорти лише позначать наявність залежностей; викликатимемо умовно
    import pyexcel_ods3  # type: ignore
except Exception:  # pragma: no cover
    pyexcel_ods3 = None  # noqa: F401

logger = logging.getLogger(__name__)


# ------------------------------ Утиліти --------------------------------------


_NUM_UA_RE = re.compile(r"^\s*([+-]?)\s*([0-9 ]+)(?:,([0-9]{1,}))?\s*$")


def parse_ua_number(text: str) -> Optional[float]:
    """
    Парсить число у форматі з пробілами як роздільниками тисяч і комою як десятковим:
        "12 345,67" -> 12345.67
        "1 234"     -> 1234.0
        "- 2,5"     -> -2.5
    Повертає float або None, якщо рядок не схожий на число.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    if not isinstance(text, str):
        return None
    m = _NUM_UA_RE.match(text)
    if not m:
        return None
    sign, int_part, frac_part = m.groups()
    int_part = int_part.replace(" ", "")
    if frac_part is None or frac_part == "":
        value = float(int_part)
    else:
        value = float(f"{int_part}.{frac_part}")
    if sign == "-":
        value = -value
    return value


def coerce_numeric_columns(df: pd.DataFrame, columns: Optional[Iterable[str]] = None) -> pd.DataFrame:
    """
    Обережно приводить вказані колонки до числового типу.
    - Якщо колонка вже числова — не чіпаємо.
    - Якщо текст і виглядає як "12 345,67" — парсимо у float.
    - Все інше лишається як є.

    Повертає той самий df (in-place).
    """
    if df is None or df.empty:
        return df

    cols = list(columns) if columns is not None else list(df.columns)
    for c in cols:
        if c not in df.columns:
            continue
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            continue
        # спробуємо м’яко конвертувати текст до float
        converted = []
        any_converted = False
        for v in s.tolist():
            if isinstance(v, (int, float)) or v is None:
                converted.append(v)
                continue
            if isinstance(v, str):
                v = v.strip()
                if v == "":
                    converted.append(None)
                    continue
                num = parse_ua_number(v)
                if num is not None:
                    converted.append(num)
                    any_converted = True
                    continue
                # fallback: спроба через replace для "1 234.56" або "1,234.56"
                try:
                    v2 = v.replace(" ", "")
                    v2 = v2.replace(",", ".") if v.count(",") == 1 and "." not in v else v2
                    converted.append(float(v2))
                    any_converted = True
                    continue
                except Exception:
                    pass
            converted.append(v)
        if any_converted:
            df[c] = pd.to_numeric(pd.Series(converted), errors="coerce")
    return df


def _ext_of(path: Union[str, Path]) -> str:
    return Path(path).suffix.lower().strip(".")


def _ensure_parent_dir(path: Union[str, Path]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


# ------------------------------ Читання --------------------------------------


@dataclass
class ReadOptions:
    """
    Додаткові параметри читання.
    - sheet: ім'я або індекс аркуша (для .xlsx/.xlsm/.ods). Для .csv ігнорується.
    - header: номер рядка заголовка (0 за замовчуванням), або None — без заголовка.
    - keep_default_na: чи трактувати стандартні маркери NA як NaN (pandas read_*).
    """
    sheet: Optional[Union[str, int]] = 0
    header: Optional[int] = 0
    keep_default_na: bool = True


def read_any_spreadsheet(path: Union[str, Path],
                         options: Optional[ReadOptions] = None) -> pd.DataFrame:
    """
    Зчитує табличний файл будь-якого підтримуваного формату у DataFrame.
    Автоматично визначає парсер за розширенням файлу.

    Для .ods використовуємо pyexcel-ods3, оскільки pandas не завжди стабільно читає ODS.
    Для .xlsx/.xlsm/.csv використовуємо pandas напряму.

    Параметри:
        path: шлях до файлу
        options: ReadOptions

    Повертає:
        pandas.DataFrame (порожній, якщо джерело порожнє)
    """
    options = options or ReadOptions()
    ext = _ext_of(path)

    if ext in ("xlsx", "xlsm"):
        df = pd.read_excel(
            str(path),
            sheet_name=options.sheet if options.sheet is not None else 0,
            header=options.header,
            engine="openpyxl"
        )
        if isinstance(df, dict):
            # якщо sheet_name=None -> повертається dict аркушів; візьмемо перший
            df = next(iter(df.values()))
        return df

    if ext == "csv":
        df = pd.read_csv(
            str(path),
            header=options.header if options.header is not None else "infer",
            keep_default_na=options.keep_default_na,
            encoding="utf-8",
            sep=None,  # autodetect (python engine)
            engine="python",
        )
        return df

    if ext == "ods":
        if pyexcel_ods3 is None:
            raise RuntimeError("Для читання .ods встановіть пакет pyexcel-ods3.")
        # Читаємо через pyexcel-ods3 → перетворюємо на DataFrame
        data = pyexcel_ods3.get_data(str(path))  # type: ignore
        # Обрати аркуш: за замовчуванням — перший
        sheet_names = list(data.keys())
        if not sheet_names:
            return pd.DataFrame()
        if options.sheet is None:
            sheet_name = sheet_names[0]
        elif isinstance(options.sheet, int):
            sheet_name = sheet_names[options.sheet] if 0 <= options.sheet < len(sheet_names) else sheet_names[0]
        else:
            sheet_name = options.sheet if options.sheet in data else sheet_names[0]

        rows: List[List[object]] = data.get(sheet_name, []) or []
        if not rows:
            return pd.DataFrame()

        header_row_idx = options.header if isinstance(options.header, int) else 0
        header_row_idx = header_row_idx if 0 <= header_row_idx < len(rows) else 0

        headers = rows[header_row_idx] if rows else []
        body = rows[header_row_idx + 1 :] if len(rows) > header_row_idx + 1 else []
        # Якщо заголовок пустий або це не список струн — зробимо штучні імена колонок
        headers = [
            (str(h).strip() if h is not None and str(h).strip() != "" else f"col_{i+1}")
            for i, h in enumerate(headers)
        ]
        df = pd.DataFrame(body, columns=headers)
        return df

    raise ValueError(f"Непідтримуваний формат: .{ext}. Доступні: .xlsx, .xlsm, .ods, .csv")


# ------------------------------ Запис ----------------------------------------


@dataclass
class WriteOptions:
    """
    Параметри запису.
    - fmt: "xlsx"|"xlsm"|"ods"|"csv" (якщо None — визначається з розширення шляху)
    - sheet_name: назва аркуша (для Excel/ODS)
    - index: чи писати індекс DataFrame
    - na_rep: як представляти NaN при записі (для CSV/ODS); для Excel це вирішує механізм движка
    - float_precision: формат float у CSV (наприклад, "%.2f"); для Excel/ODS — не застосовується тут
    """
    fmt: Optional[str] = None
    sheet_name: str = "Sheet1"
    index: bool = False
    na_rep: Optional[str] = None
    float_precision: Optional[str] = None


def write_any_spreadsheet(df: pd.DataFrame,
                          path: Union[str, Path],
                          options: Optional[WriteOptions] = None) -> None:
    """
    Записує DataFrame у файл вибраного формату.
    Якщо формат не вказано, визначається з розширення шляху.

    Зауваження:
    - Ми не нав’язуємо локальне форматування чисел у Excel/ODS (це завдання для UI/шаблонів).
      Тут записуються «чисті» числові типи — Excel/Libre самі відобразять як слід.
    """
    if df is None:
        df = pd.DataFrame()
    options = options or WriteOptions()
    fmt = (options.fmt or _ext_of(path)).lower()
    _ensure_parent_dir(path)

    if fmt in ("xlsx", "xlsm"):
        # Віддаємо перевагу xlsxwriter для кращої продуктивності; fallback на openpyxl.
        try:
            with pd.ExcelWriter(str(path), engine="xlsxwriter") as writer:
                df.to_excel(writer, sheet_name=options.sheet_name, index=options.index)
        except Exception:
            with pd.ExcelWriter(str(path), engine="openpyxl") as writer:  # fallback
                df.to_excel(writer, sheet_name=options.sheet_name, index=options.index)
        return

    if fmt == "csv":
        df.to_csv(
            str(path),
            index=options.index,
            encoding="utf-8",
            lineterminator="\n",
            na_rep=options.na_rep if options.na_rep is not None else "",
            float_format=options.float_precision,
        )
        return

    if fmt == "ods":
        if pyexcel_ods3 is None:
            raise RuntimeError("Для запису .ods встановіть пакет pyexcel-ods3.")
        # Перетворюємо DataFrame у двовимірний список: [headers] + rows
        headers = list(map(str, df.columns.tolist()))
        rows = [headers] + df.astype(object).where(pd.notnull(df), None).values.tolist()  # None → порожня клітинка
        # pyexcel-ods3 записує словник {sheet_name: rows}
        from pyexcel_ods3 import save_data  # type: ignore
        data = {options.sheet_name: rows}
        save_data(str(path), data)
        return

    raise ValueError(f"Непідтримуваний формат запису: {fmt}")


# --------------------------- Зручні обгортки ---------------------------------


def read_and_sanitize(path: Union[str, Path],
                      numeric_columns: Optional[Iterable[str]] = None,
                      options: Optional[ReadOptions] = None) -> pd.DataFrame:
    """
    Зручна обгортка: прочитати файл і привести вказані колонки до числового типу
    з урахуванням локального запису чисел ("12 345,67").
    """
    df = read_any_spreadsheet(path, options=options)
    if numeric_columns:
        coerce_numeric_columns(df, numeric_columns)
    return df


def write_table(df: pd.DataFrame,
                path: Union[str, Path],
                fmt: Optional[str] = None,
                sheet_name: str = "Sheet1",
                index: bool = False,
                na_rep: Optional[str] = None,
                float_precision: Optional[str] = None) -> None:
    """
    Спрощений запис таблиці без створення WriteOptions вручну.
    """
    opts = WriteOptions(fmt=fmt, sheet_name=sheet_name, index=index,
                        na_rep=na_rep, float_precision=float_precision)
    write_any_spreadsheet(df, path, options=opts)


# ------------------------------ Тести (скелет) -------------------------------

if __name__ == "__main__":  # ручний швидкий прогін
    # Невеличка самоперевірка парсингу чисел
    samples = ["12 345,67", "1 234", "- 2,5", "0", "  123  ", "abc", None]
    for s in samples:
        print(f"{s!r} -> {parse_ua_number(s)}")
    # Тест читання/запису можна зробити окремо у тестах pytest