"""Request-scoped UI settings (language, theme) and the Jinja environment."""
from functools import partial
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.i18n import LANG_NAMES, format_date, format_qty, translate

THEMES = ("dark", "light")


def request_lang(request: Request) -> str:
    s = get_settings()
    lang = request.cookies.get("lang")
    return lang if lang in s.languages else s.default_lang


def request_theme(request: Request) -> str:
    theme = request.cookies.get("theme")
    return theme if theme in THEMES else "dark"


def _context(request: Request) -> dict:
    lang = request_lang(request)
    s = get_settings()
    return {
        "lang": lang,
        "theme": request_theme(request),
        "languages": [(code, LANG_NAMES.get(code, code)) for code in s.languages],
        "t": partial(translate, lang),
        "qty": lambda v: format_qty(v, lang),
        "fmt_date": lambda v: format_date(v, lang),
        "llm_enabled": s.llm_configured,
        "shopping_enabled": s.shopping_enabled,
    }


templates = Jinja2Templates(
    directory=Path(__file__).parent / "templates", context_processors=[_context]
)
