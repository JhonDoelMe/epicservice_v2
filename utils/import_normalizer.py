# -*- coding: utf-8 -*-
"""
Нормалізація імпортів для бота.

Мета:
- Привести вхідні таблиці (xlsx/xlsm/ods/csv) до єдиної схеми колонок.
- Підтримати широкий набір синонімів заголовків (укр/рос/англ, короткі мітки).
- Якщо немає явної колонки "артикул", спробувати витягти його з початку "назви" (перші 8 цифр).
- Привести числові поля до типу number, враховуючи локальні формати ("12 345,67").
- Автоматично добити відсутні "сума" та/або "ціна", якщо це можливо.
- Повернути зручну структуру результату з попередженнями й аудит-звітом.

Канонічні назви колонок (після нормалізації):
    - "відділ"         (int/str)      — код відділу
    - "група"          (str)          — назва групи (опційно)
    - "артикул"        (str)          — 8-значний код (рядок, зберігаємо ведучі нулі)
    - "назва"          (str)          — найменування товару
    - "місяців без руху" (int/float)  — скільки місяців товар без руху (опційно)
    - "кількість"      (int/float)    — кількість
    - "ціна"           (float)        — ціна за одиницю
    - "сума"           (float)        — загальна сума (кількість * ціна)

Мінімально достатній набір колонок для імпорту:
    - "артикул" І "назва"  І принаймні одна з ("кількість", "сума", "ціна")
    - Якщо "артикул" відсутній, але його можна витягти з "назви" — приймаємо.

Якщо після всіх спроб не знайдено ЖОДНОГО артикулу — імпорт скасовується (виняток NoArticlesError).

Примітка:
- Усі помічені під час нормалізації відповідності заголовків зберігаються у "mapping_report",
  щоб адміністратор бачив, як саме були мапнуті синоніми.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

# М'яке приведення чисел використовуємо з утиліт вводу/виводу
try:
    from .io_spreadsheet import coerce_numeric_columns
except Exception:
    # Фолбек, якщо модуль не під рукою (наприклад, при окремому тестуванні)
    def coerce_numeric_columns(df: pd.DataFrame, columns=None) -> pd.DataFrame:
        return df

__all__ = [
    "NoArticlesError",
    "NormalizedImport",
    "normalize_import_table",
]


# ---------------------------- Константи/синоніми -----------------------------

# Увага: тут спеціально багато варіантів під різні джерела (укр/рос/англ).
SYNONYMS: Dict[str, Sequence[str]] = {
    "відділ": [
        "відділ", "в", "dept", "department", "отдел", "отд", "відд", "division",
    ],
    "група": [
        "група", "гр", "group", "категорія", "категория", "category", "grp",
    ],
    "артикул": [
        "артикул", "а", "код", "sku", "article", "item", "код товару", "товар.код",
        "код_товара", "код_товару", "barcode", "штрихкод", "штрих-код",
    ],
    "назва": [
        "назва", "найменування", "найм", "наименование", "name", "товар", "опис", "описание", "title", "product",
    ],
    "місяців без руху": [
        "місяців без руху", "міс без руху", "без руху (міс)", "м", "months without move",
        "months_no_move", "months", "months idle", "idle months", "без руху", "міс",
    ],
    "кількість": [
        "кількість", "к-сть", "к", "qty", "quantity", "кол-во", "количество", "pcs", "шт", "amount",
    ],
    "ціна": [
        "ціна", "ц", "price", "цена", "грн/од", "uah/pcs", "unit price", "unit_price",
    ],
    "сума": [
        "сума", "с", "amount", "sum", "всього", "итого", "total", "total price", "total_price", "value",
    ],
}

# Порядок важливий: спершу шукаємо ці, далі інші
CANON_ORDER = [
    "відділ",
    "група",
    "артикул",
    "назва",
    "місяців без руху",
    "кількість",
    "ціна",
    "сума",
]

# Артикул: рівно 8 цифр на початку назви — наш стандарт
ARTICLE_RE = re.compile(r"^\s*(\d{8})\b")


# ------------------------------- Винятки -------------------------------------

class NoArticlesError(RuntimeError):
    """Жодного артикулу не виявлено після нормалізації."""


# ----------------------------- Результат -------------------------------------

@dataclass
class NormalizedImport:
    """
    Результат нормалізації імпорту.
    """
    df: pd.DataFrame
    mapping_report: Dict[str, str]                 # {канонічна_колонка: виявлений_вхідний_заголовок}
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, float] = field(default_factory=dict)  # довільні числові метрики (за бажанням)

    def require_any_articles(self) -> "NormalizedImport":
        """
        Підіймає NoArticlesError, якщо після нормалізації немає жодного валідного артикулу.
        """
        if self.df.empty or "артикул" not in self.df.columns or self.df["артикул"].isna().all():
            raise NoArticlesError("Імпорт скасовано: не знайдено жодного артикула.")
        return self


# --------------------------- Допоміжні функції -------------------------------

def _normalize_header(h: str) -> str:
    """Нормалізувати заголовок: пробіли, нижній регістр, прибрати сміття."""
    if h is None:
        return ""
    s = str(h).strip().lower()
    # Часті небажані символи у заголовках
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s)
    return s


def _build_reverse_index() -> Dict[str, str]:
    """
    Побудувати мапу від нормалізованого вхідного заголовка до канонічного імені.
    Якщо конфлікт — перемагає перша по CANON_ORDER канонічна колонка.
    """
    rev: Dict[str, str] = {}
    for canon in CANON_ORDER:
        for var in SYNONYMS.get(canon, []):
            key = _normalize_header(var)
            rev.setdefault(key, canon)
    return rev


REV_INDEX = _build_reverse_index()


def _match_headers(raw_headers: Sequence[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Підібрати відповідності заголовків.
    Повертає:
      - mapping: {canon: source_header or "" (якщо не знайдено)}
      - reverse: {source_header: canon} (тільки для знайдених)
    """
    mapping: Dict[str, str] = {c: "" for c in CANON_ORDER}
    reverse: Dict[str, str] = {}
    norm_map = {h: _normalize_header(h) for h in raw_headers}

    # 1) Пробуємо точне співпадіння через REV_INDEX
    for h, norm in norm_map.items():
        if norm in REV_INDEX:
            canon = REV_INDEX[norm]
            if not mapping[canon]:  # ще не зайнято
                mapping[canon] = h
                reverse[h] = canon

    # 2) Якщо щось лишилося — м'яка евристика по підрядку
    for canon in CANON_ORDER:
        if mapping[canon]:
            continue
        for h, norm in norm_map.items():
            if h in reverse:
                continue
            # прості евристики: "назва", "наименование", "name" тощо — часткові збіги
            for syn in SYNONYMS.get(canon, []):
                if _normalize_header(syn) in norm or norm in _normalize_header(syn):
                    mapping[canon] = h
                    reverse[h] = canon
                    break
            if mapping[canon]:
                break

    return mapping, reverse


def _extract_article_from_name(name: str) -> Optional[str]:
    """
    Витягти артикул з початку назви (перші рівно 8 цифр).
    Повертає рядок з 8 символами або None.
    """
    if not isinstance(name, str):
        return None
    m = ARTICLE_RE.match(name)
    if not m:
        return None
    return m.group(1)


def _ensure_article_as_str(df: pd.DataFrame) -> pd.DataFrame:
    """
    Привести артикул до РЯДКА (щоб не загубити ведучі нулі).
    Обрізаємо пробіли; невалідні значення → None.
    """
    if "артикул" not in df.columns:
        return df
    vals = []
    for v in df["артикул"].tolist():
        if v is None or (isinstance(v, float) and pd.isna(v)):
            vals.append(None)
            continue
        s = str(v).strip()
        # Артикул у нас стандартно 8 цифр, але інколи трапляються "00012345.0"
        s = s.split(".")[0] if re.fullmatch(r"\d+(\.0+)?", s) else s
        if re.fullmatch(r"\d{8}", s):
            vals.append(s)
        else:
            vals.append(None)
    df["артикул"] = pd.Series(vals, index=df.index)
    return df


def _recompute_price_sum(df: pd.DataFrame) -> pd.DataFrame:
    """
    Добити відсутні "сума" та/або "ціна", якщо можемо.
    Правила:
      - якщо є "кількість" і "ціна", але немає "сума" → сума = кількість * ціна
      - якщо є "кількість" і "сума", але немає "ціна" → ціна = сума / кількість (де кількість > 0)
      - якщо є лише одне з полів — залишаємо як є
    """
    cols = df.columns
    has_qty = "кількість" in cols
    has_price = "ціна" in cols
    has_sum = "сума" in cols

    if not (has_qty or has_price or has_sum):
        return df

    if has_qty and has_price:
        # сума, якщо відсутня
        if has_sum:
            mask = df["сума"].isna() & df["кількість"].notna() & df["ціна"].notna()
            df.loc[mask, "сума"] = df.loc[mask, "кількість"] * df.loc[mask, "ціна"]
        else:
            df["сума"] = df["кількість"] * df["ціна"]
            has_sum = True

    if has_qty and has_sum and not has_price:
        mask = df["кількість"].notna() & (df["кількість"].astype(float) != 0) & df["сума"].notna()
        price = pd.Series([None] * len(df), index=df.index, dtype="float64")
        price.loc[mask] = df.loc[mask, "сума"] / df.loc[mask, "кількість"]
        df["ціна"] = price
        has_price = True

    return df


# ------------------------------ Основна функція ------------------------------

def normalize_import_table(raw_df: pd.DataFrame) -> NormalizedImport:
    """
    Головна функція нормалізації імпорту.

    Кроки:
      1) Обрізати порожні рядки/стіни пробілів.
      2) Розпізнати заголовки → спроєктувати на канонічні колонки.
      3) Перейменувати колонки згідно зі знайденим мапінгом.
      4) Якщо артикулу немає — спробувати витягти з назви (перші 8 цифр).
      5) Привести числа до numeric (кількість/ціна/сума/місяців без руху).
      6) Добити відсутні "сума"/"ціна" (де можливо).
      7) Почистити явний треш: рядки без назви і без артикула відкинути.
      8) Повернути результат + звіт по мапінгу та попередження.

    Повертає:
      NormalizedImport(df=..., mapping_report=..., warnings=[...], stats={...})
    """
    warnings: List[str] = []

    if raw_df is None or raw_df.empty:
        return NormalizedImport(df=pd.DataFrame(columns=CANON_ORDER), mapping_report={}, warnings=["Порожній файл."])

    # 1) Приберемо "порожні" рядки, де всі клітинки пусті/NaN
    df = raw_df.copy()
    df = df.dropna(how="all")
    if df.empty:
        return NormalizedImport(df=pd.DataFrame(columns=CANON_ORDER), mapping_report={}, warnings=["Усі рядки порожні."])

    # 2) Визначити відповідності заголовків
    raw_headers = list(map(str, df.columns.tolist()))
    mapping, reverse = _match_headers(raw_headers)

    mapping_report = {canon: src for canon, src in mapping.items() if src}
    # Зафіксуємо відсутні
    for canon in CANON_ORDER:
        if not mapping.get(canon):
            warnings.append(f"Не знайдено колонку «{canon}». Спробую компенсувати, якщо можливо.")

    # 3) Перейменування знайдених
    rename_map = {src: canon for canon, src in mapping.items() if src}
    df = df.rename(columns=rename_map)

    # 4) Якщо немає "артикул", але є "назва" — спробуємо витягти
    if "артикул" not in df.columns and "назва" in df.columns:
        articles: List[Optional[str]] = []
        for name in df["назва"].tolist():
            art = _extract_article_from_name(name)
            articles.append(art)
        df["артикул"] = pd.Series(articles, index=df.index)
        mapping_report.setdefault("артикул", "(витягнуто з «назва»)")
        warnings.append("Колонка «артикул» відсутня. Отримано з початку «назви» перші 8 цифр, де це вдалося.")

    # 5) Привести артикул до рядка з 8 цифрами (інші → None)
    df = _ensure_article_as_str(df)

    # 6) Привести числа
    num_cols = [c for c in ("кількість", "ціна", "сума", "місяців без руху") if c in df.columns]
    if num_cols:
        coerce_numeric_columns(df, num_cols)

    # 7) Добити "сума"/"ціна", якщо можемо
    df = _recompute_price_sum(df)

    # 8) Базова очистка: викинути рядки без "назва" і без "артикул" (тобто зовсім порожні товари)
    def _is_blank(x) -> bool:
        return x is None or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and x.strip() == "")

    keep_mask = ~(
        (("назва" not in df.columns) or df["назва"].apply(_is_blank)) &
        (("артикул" not in df.columns) or df["артикул"].apply(_is_blank))
    )
    df = df.loc[keep_mask].copy()

    # 9) Обрізати пробіли у назвах/групах
    for col in ("назва", "група"):
        if col in df.columns:
            df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)

    # 10) Порахувати прості метрики
    total_rows = int(len(df))
    unique_articles = int(df["артикул"].dropna().astype(str).nunique()) if "артикул" in df.columns else 0

    stats = {
        "rows_total": float(total_rows),
        "articles_unique": float(unique_articles),
    }

    # 11) Відкинути рядки, де артикул не визначився зовсім
    if "артикул" in df.columns:
        df = df[df["артикул"].notna()].copy()

    # 12) Якщо після всього жодного артикулу — фатальна помилка
    result = NormalizedImport(df=df, mapping_report=mapping_report, warnings=warnings, stats=stats)
    result.require_any_articles()

    # 13) Впорядкувати колонки за каноном (де є)
    ordered = [c for c in CANON_ORDER if c in result.df.columns]
    other = [c for c in result.df.columns if c not in ordered]
    result.df = result.df[ordered + other]

    return result
