"""Request-scoped UI settings (language, theme) and the Jinja environment."""
from functools import partial
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import categories, units
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
        "amount": lambda q, unit, **kw: units.amount(q, unit, lang, **kw),
        "unit_label": lambda code: units.label(code, lang),
        "unit_options": units.options(lang),
        "category_options": categories.options(lang),
        "category_label": lambda code: categories.label(code, lang),
        "fmt_date": lambda v: format_date(v, lang),
        "llm_enabled": s.llm_configured,
        "shopping_enabled": s.shopping_configured,
        "current_user": getattr(request.state, "user", None),
    }


templates = Jinja2Templates(
    directory=Path(__file__).parent / "templates", context_processors=[_context]
)


def device_name(user_agent: str) -> str:
    """Rough 'Browser on OS' label for the logged-in devices list."""
    ua = user_agent or ""
    os_name = next((label for key, label in (
        ("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
        ("Mac OS X", "Mac"), ("Macintosh", "Mac"), ("Linux", "Linux"),
    ) if key in ua), "")
    browser = next((label for key, label in (
        ("Edg/", "Edge"), ("Firefox/", "Firefox"), ("CriOS", "Chrome"), ("Chrome/", "Chrome"),
        ("Safari/", "Safari"),
    ) if key in ua), "")
    if browser and os_name:
        return f"{browser} · {os_name}"
    return browser or os_name or (ua[:40] if ua else "?")


templates.env.filters["device"] = device_name
