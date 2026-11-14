"""Извлечение дат и временных интервалов из текста запроса.

Соответствует спецификации раздела 5.6 (R5) planchik.md:
- Точные даты (день, месяц, год): '15 октября 2024', '01.09.2026', 'с 1 января 2026 г.'
- Месяц и год: 'в августе 2024 года', 'в апреле 2025'
- Год: 'в 2024 году', 'за 2025 год', 'на 2026 год'
- Относительные даты: 'сейчас', 'сегодня', 'в настоящее время'
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from typing import Literal

MONTHS_MAP = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}


@dataclass
class DateExtractionResult:
    as_of: str | None  # "YYYY-MM-DD" если однозначно, или первая дата диапазона
    as_of_range: tuple[str, str] | None  # (start_iso, end_iso)
    precision: Literal["day", "month", "year", "current", "none"]
    raw_match: str | None


def extract_dates(text: str) -> DateExtractionResult:
    """Извлекает дату события или временной диапазон из текста."""
    t_clean = text.lower().replace("ё", "е")

    # 1. Проверка на относительные даты ("сейчас", "сегодня", "текущая")
    if any(w in t_clean for w in ("сейчас", "сегодня", "в настоящее время", "на текущий момент", "текущая редакция")):
        return DateExtractionResult(
            as_of=None,
            as_of_range=None,
            precision="current",
            raw_match="сейчас",
        )

    # 2. Точная дата вида DD.MM.YYYY (например, 15.10.2024 или 01.09.2026)
    match_dd_mm_yyyy = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", t_clean)
    if match_dd_mm_yyyy:
        day = int(match_dd_mm_yyyy.group(1))
        month = int(match_dd_mm_yyyy.group(2))
        year = int(match_dd_mm_yyyy.group(3))
        iso_str = f"{year:04d}-{month:02d}-{day:02d}"
        return DateExtractionResult(
            as_of=iso_str,
            as_of_range=(iso_str, iso_str),
            precision="day",
            raw_match=match_dd_mm_yyyy.group(0),
        )

    # 3. Точная дата прописью: "15 октября 2024", "1 января 2026 г.", "3 сентября 2024 года"
    month_pattern = "|".join(MONTHS_MAP.keys())
    match_word_date = re.search(
        rf"\b(?:с|на|до|от)?\s*(\d{{1,2}})\s+({month_pattern})[а-я]*\s+(\d{{4}})(?:\s*г(?:ода?)?)?\b",
        t_clean,
    )
    if match_word_date:
        day = int(match_word_date.group(1))
        m_root = match_word_date.group(2)
        month = MONTHS_MAP[m_root]
        year = int(match_word_date.group(3))
        iso_str = f"{year:04d}-{month:02d}-{day:02d}"
        return DateExtractionResult(
            as_of=iso_str,
            as_of_range=(iso_str, iso_str),
            precision="day",
            raw_match=match_word_date.group(0),
        )

    # 4. Месяц и год: "в августе 2024 года", "в апреле 2025", "июне 2026 года"
    match_month_year = re.search(
        rf"\b(?:в|к|на|с|за)?\s*({month_pattern})[а-я]*\s+(\d{{4}})(?:\s*г(?:ода?)?)?\b",
        t_clean,
    )
    if match_month_year:
        m_root = match_month_year.group(1)
        month = MONTHS_MAP[m_root]
        year = int(match_month_year.group(2))
        _, last_day = calendar.monthrange(year, month)
        start_iso = f"{year:04d}-{month:02d}-01"
        end_iso = f"{year:04d}-{month:02d}-{last_day:02d}"
        return DateExtractionResult(
            as_of=start_iso,
            as_of_range=(start_iso, end_iso),
            precision="month",
            raw_match=match_month_year.group(0),
        )

    # 5. Год: "в 2024 году", "за 2025 год", "на 2026 год", "в 2025 г."
    match_year = re.search(r"\b(?:в|за|на|с)?\s*(\d{4})\s*(?:г(?:оду?|ода?)?)\b", t_clean)
    if match_year:
        year = int(match_year.group(1))
        start_iso = f"{year:04d}-01-01"
        end_iso = f"{year:04d}-12-31"
        return DateExtractionResult(
            as_of=start_iso,
            as_of_range=(start_iso, end_iso),
            precision="year",
            raw_match=match_year.group(0),
        )

    # Год без слова "год", если 4 цифры в юридическом диапазоне (2020..2030)
    match_standalone_year = re.search(r"\b(202[0-9])\b", t_clean)
    if match_standalone_year:
        year = int(match_standalone_year.group(1))
        start_iso = f"{year:04d}-01-01"
        end_iso = f"{year:04d}-12-31"
        return DateExtractionResult(
            as_of=start_iso,
            as_of_range=(start_iso, end_iso),
            precision="year",
            raw_match=match_standalone_year.group(0),
        )

    return DateExtractionResult(
        as_of=None,
        as_of_range=None,
        precision="none",
        raw_match=None,
    )
