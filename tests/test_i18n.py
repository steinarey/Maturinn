import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.i18n import CATALOG_DIR, format_qty, parse_qty, translate

ROOT = Path(__file__).resolve().parents[1] / "app"


def load(lang):
    return json.loads((CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def test_catalogs_have_same_keys():
    assert set(load("is")) == set(load("en"))


def test_every_used_key_exists():
    keys = set(load("en"))
    used = set()
    for f in (ROOT / "templates").rglob("*.html"):
        used |= set(re.findall(r"\bt\('([a-z_.]+)'", f.read_text(encoding="utf-8")))
    for f in ROOT.rglob("*.py"):
        used |= set(re.findall(r'"(error\.[a-z_]+)"', f.read_text(encoding="utf-8")))
    static = {k for k in used if not k.endswith(".")}
    prefixes = {k for k in used if k.endswith(".")}
    assert static - keys == set()
    for p in prefixes:  # dynamic keys like 'lang.' ~ code
        assert any(k.startswith(p) for k in keys), p


def test_fallback_to_english_then_key():
    assert translate("is", "nav.recipes") == "Uppskriftir"
    assert translate("de", "nav.recipes") == "Recipes"
    assert translate("is", "no.such.key") == "no.such.key"


@pytest.mark.parametrize("text,value", [
    ("2", Decimal("2")), ("1,5", Decimal("1.5")), ("1.5", Decimal("1.5")),
    ("1/2", Decimal("0.5")), ("1 1/2", Decimal("1.5")), ("1½", Decimal("1.5")),
    ("", None), ("  ", None),
])
def test_parse_qty(text, value):
    assert parse_qty(text) == value


@pytest.mark.parametrize("text", ["tvö", "1/0", "1.5/2", "2 dl"])
def test_parse_qty_rejects(text):
    with pytest.raises(ValueError):
        parse_qty(text)


def test_format_qty_locale():
    assert format_qty(Decimal("1.500"), "is") == "1,5"
    assert format_qty(Decimal("1.500"), "en") == "1.5"
    assert format_qty(Decimal("1000"), "is") == "1000"
    assert format_qty(None, "is") == ""


def test_default_language_is_icelandic_and_switch(client):
    r = client.get("/")
    assert '<html lang="is" data-theme="dark">' in r.text
    r = client.get("/set-lang/en", headers={"referer": "http://testserver/recipes/new"},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/recipes/new"
    client.cookies.set("lang", "en")
    assert '<html lang="en"' in client.get("/").text


def test_theme_cookie(client):
    client.cookies.set("theme", "light")
    assert 'data-theme="light"' in client.get("/").text
    client.cookies.set("theme", "bogus")
    assert 'data-theme="dark"' in client.get("/").text
