"""UI translation catalogs and locale-aware formatting.

Catalogs are flat JSON files in app/i18n/<lang>.json. Lookup falls back
from the requested language to English, then to the key itself.
"""
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from babel.dates import format_date as _babel_date
from babel.numbers import format_decimal

CATALOG_DIR = Path(__file__).parent / "i18n"
FALLBACK = "en"
BABEL_LOCALES = {"is": "is_IS", "en": "en_GB"}
LANG_NAMES = {"is": "Íslenska", "en": "English"}


@lru_cache
def catalog(lang: str) -> dict[str, str]:
    path = CATALOG_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def translate(lang: str, key: str, **kwargs) -> str:
    text = catalog(lang).get(key) or catalog(FALLBACK).get(key) or key
    return text.format(**kwargs) if kwargs else text


def format_qty(value: Decimal | float | int | None, lang: str) -> str:
    """1.500 -> '1,5' in is, '1.5' in en. No grouping, up to 3 decimals."""
    if value is None:
        return ""
    return format_decimal(Decimal(value), format="0.###", locale=BABEL_LOCALES.get(lang, "en_GB"))


def format_date(value: date | datetime | None, lang: str) -> str:
    if value is None:
        return ""
    return _babel_date(value, format="long", locale=BABEL_LOCALES.get(lang, "en_GB"))


_UNICODE_FRACTIONS = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅛": "1/8"}


def parse_qty(text: str | None) -> Decimal | None:
    """Accept '1,5', '1.5', '1/2', '1 1/2', '1½'. Empty -> None. Garbage -> ValueError."""
    if text is None:
        return None
    s = text.strip()
    if not s:
        return None
    for k, v in _UNICODE_FRACTIONS.items():
        s = s.replace(k, f" {v}")
    s = s.replace(",", ".").strip()
    try:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)?\s*(?:(\d+)\s*/\s*(\d+))?", s)
        if not m or not s:
            raise ValueError(text)
        whole, num, den = m.groups()
        total = Decimal(whole) if whole else Decimal(0)
        if num:
            if whole and "." in whole:
                raise ValueError(text)
            total += Decimal(num) / Decimal(den)
        return total.quantize(Decimal("0.001")).normalize() if num else total
    except (InvalidOperation, ZeroDivisionError) as e:
        raise ValueError(text) from e
