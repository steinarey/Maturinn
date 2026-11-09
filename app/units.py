"""Units of measurement.

Ingredient units are stored as language-neutral codes ('tsp', 'cup', 'g') and shown
translated ('tsk', 'bollar'). Two entry points:

- canonical(qty, raw): what gets stored. Maps what people and recipes write ('msk',
  'Tablespoons', 'T', 'tsk.') to a code, and converts units we don't use (oz, lb,
  fl oz, pint, quart, gallon, stick of butter, cl) to g or ml. A unit we don't know
  is kept as written.
- amount(qty, code, lang, ...): what gets shown. Picks the friendliest unit in the
  same family after scaling: 3 tsk -> 1 msk, 1500 g -> 1,5 kg, 10 dl -> 1 l,
  1/3 msk -> 1 tsk. It only changes the unit when the number comes out round, so
  4 tsk stays 4 tsk rather than becoming 1 1/3 msk.

Families never mix: volume isn't converted to weight (that needs a density per
ingredient). Spoons, cups and metric volume are separate families too, so a recipe
written in dl doesn't sprout spoons. Cups switch to dl/ml only when asked (metric=True).
"""
from dataclasses import dataclass
from decimal import Decimal

from app.i18n import format_qty


@dataclass(frozen=True)
class Unit:
    code: str
    family: str | None  # spoon, cup, metric (volume), mass; None = counted, never converted
    base: float  # size in ml (volume) or g (mass)
    names: dict[str, tuple[str, str]]  # lang -> (singular, plural)


def _u(code, family, base, is_, en):
    return Unit(code, family, base, {"is": is_, "en": en})


# In the order shown in the editor's unit picker.
UNITS: dict[str, Unit] = {u.code: u for u in [
    _u("tsp", "spoon", 5, ("tsk", "tsk"), ("tsp", "tsp")),
    _u("tbsp", "spoon", 15, ("msk", "msk"), ("tbsp", "tbsp")),
    _u("dl", "metric", 100, ("dl", "dl"), ("dl", "dl")),
    _u("cup", "cup", 240, ("bolli", "bollar"), ("cup", "cups")),  # US cup, 16 tbsp
    _u("ml", "metric", 1, ("ml", "ml"), ("ml", "ml")),
    _u("l", "metric", 1000, ("l", "l"), ("l", "l")),
    _u("g", "mass", 1, ("g", "g"), ("g", "g")),
    _u("kg", "mass", 1000, ("kg", "kg"), ("kg", "kg")),
    _u("pc", None, 1, ("stk", "stk"), ("pc", "pcs")),
    _u("pinch", None, 1, ("klípa", "klípur"), ("pinch", "pinches")),
    _u("dash", None, 1, ("skvetta", "skvettur"), ("dash", "dashes")),
    _u("clove", None, 1, ("rif", "rif"), ("clove", "cloves")),
    _u("can", None, 1, ("dós", "dósir"), ("can", "cans")),
    _u("package", None, 1, ("pakki", "pakkar"), ("package", "packages")),
    _u("slice", None, 1, ("sneið", "sneiðar"), ("slice", "slices")),
    _u("bunch", None, 1, ("búnt", "búnt"), ("bunch", "bunches")),
    _u("handful", None, 1, ("handfylli", "handfylli"), ("handful", "handfuls")),
]}

# Other spellings, in addition to every unit's own names. Keys are normalized (see _norm).
_ALIASES = {
    "tsp": "teaspoon teaspoons tsps teskeið teskeiðar teskeiðum",
    "tbsp": "tablespoon tablespoons tbs tbl tbsps matskeið matskeiðar matskeiðum",
    "dl": "deciliter deciliters decilitre decilitres desilítri desilítrar desilítra",
    "cup": "c bolla bollum",
    "ml": "milliliter milliliters millilitre millilitres millilítri millilítrar millilítra",
    "l": "liter liters litre litres lítri lítrar lítra",
    "g": "gr gram grams gramm grömm grömmum",
    "kg": "kilo kilos kilogram kilograms kíló kílógramm kílóum",
    "pc": "pcs piece pieces stykki",
    "pinch": "hnífsoddur hnífsodd hnífsoddar klípu",
    "dash": "skvettu",
    "clove": "",
    "can": "tin tins dósum",
    "package": "pack packs pkg pk pakka pökkum",
    "slice": "sneiðum",
    "bunch": "knippi",
    "handful": "lúka lúkur",
}

# Units we convert away on save: unit -> (code, factor).
_CONVERT = {
    **dict.fromkeys("oz ounce ounces".split(), ("g", 28.3495)),
    **dict.fromkeys("lb lbs pound pounds".split(), ("g", 453.592)),
    **dict.fromkeys(["fl oz", "floz", "fluid ounce", "fluid ounces"], ("ml", 29.5735)),
    **dict.fromkeys("pint pints pt".split(), ("ml", 473.176)),
    **dict.fromkeys("quart quarts qt".split(), ("ml", 946.353)),
    **dict.fromkeys("gallon gallons gal".split(), ("ml", 3785.41)),
    **dict.fromkeys("stick sticks".split(), ("g", 113)),  # US stick of butter
    **dict.fromkeys("cl centiliter centilitre sentilítri".split(), ("ml", 10)),
    "cc": ("ml", 1),
}


def _norm(raw: str) -> str:
    return " ".join(raw.replace(".", " ").split()).casefold()


_LOOKUP: dict[str, str] = {}
for _unit in UNITS.values():
    for _code in [_unit.code, *(n for pair in _unit.names.values() for n in pair), *_ALIASES[_unit.code].split()]:
        _LOOKUP.setdefault(_norm(_code), _unit.code)


def code_for(raw: str) -> str | None:
    """Code of a known unit, else None. Capital 'T' is tablespoon, small 't' teaspoon."""
    s = raw.strip().rstrip(".")
    if s in ("T", "Tb", "TB"):
        return "tbsp"
    if s == "t":
        return "tsp"
    return _LOOKUP.get(_norm(s))


def canonical(qty: Decimal | None, raw: str) -> tuple[Decimal | None, str]:
    """(quantity, unit) as stored: a unit code, imperial converted, or the unit as written."""
    raw = (raw or "").strip()
    if not raw:
        return qty, ""
    code = code_for(raw)
    if code:
        return qty, code
    conv = _CONVERT.get(_norm(raw))
    if conv:
        code, factor = conv
        if qty is None:
            return None, code
        v = float(qty) * factor
        return Decimal(str(round(v) if v >= 10 else round(v, 1))), code
    return qty, raw


def label(code: str, lang: str, value: float | None = None) -> str:
    """Unit name in `lang`; plural when the amount calls for it. Unknown units as written."""
    unit = UNITS.get(code)
    if not unit:
        return code
    singular, plural = unit.names.get(lang) or unit.names["en"]
    return singular if value is None or _singular(value, lang) else plural


def _singular(v: float, lang: str) -> bool:
    if v <= 1:
        return True
    # Icelandic: 21 bolli, 31 bolli, but 11 bollar.
    return lang == "is" and v == int(v) and int(v) % 10 == 1 and int(v) % 100 != 11


# --- choosing the unit to show ------------------------------------------------------

# Per unit: (smallest amount worth showing in it, the steps it's measured in).
# Spoons and cups go in fractions; metric units in decimals.
_FIT = {
    "l": (1, (100,)), "dl": (1, (10,)), "ml": (0, None),
    "kg": (1, (100,)), "g": (0, None),
    "cup": (0.25, (4, 3)), "tbsp": (0.5, (2,)), "tsp": (0, (8,)),
}
# Units to try, biggest first. Ends with the unit that takes whatever's left.
_LADDERS = {
    "spoon": ("l", "dl", "tbsp", "tsp"),
    "cup": ("cup", "tbsp", "tsp"),
    "metric": ("l", "dl", "ml"),
    "mass": ("kg", "g"),
}
_GLYPHS = {1/8: "⅛", 1/4: "¼", 1/3: "⅓", 3/8: "⅜", 1/2: "½", 5/8: "⅝", 2/3: "⅔", 3/4: "¾", 7/8: "⅞"}


def _snap(v: float, steps: tuple[int, ...], tol: float) -> float | None:
    """v rounded to the nearest 1/step, if that's within `tol` (relative)."""
    best = None
    for d in steps:
        n = round(v * d)
        if n > 0 and abs(n / d - v) <= tol * v and (best is None or abs(n / d - v) < abs(best - v)):
            best = n / d
    return best


def _fraction(v: float, lang: str) -> str:
    snapped = _snap(v, (2, 3, 4, 8), 0.05)
    if snapped is None:
        return format_qty(Decimal(str(round(v, 2))), lang)
    whole = int(snapped + 1e-9)
    rest = round(snapped - whole, 6)
    glyph = next((g for f, g in _GLYPHS.items() if abs(f - rest) < 1e-6), None)
    if rest < 1e-6:
        return str(whole)
    if glyph is None:
        return format_qty(Decimal(str(round(snapped, 2))), lang)
    return f"{whole}{glyph}" if whole else glyph


def _decimal(v: float, lang: str) -> str:
    places = 0 if v >= 10 else 1 if v >= 1 else 2
    return format_qty(Decimal(str(round(v, places))), lang)


def family(code: str, metric: bool = False) -> str:
    """Group key: amounts in the same family can be added up (shopping list)."""
    unit = UNITS.get(code)
    if unit and unit.family:
        return "metric" if unit.family == "cup" and metric else unit.family
    return "unit:" + code


def to_base(qty: float, code: str) -> float:
    unit = UNITS.get(code)
    return qty * unit.base if unit and unit.family else qty


def present(fam: str, value: float, lang: str) -> str:
    """Text for `value` (ml or g for convertible families, else a count) in the best unit."""
    if fam.startswith("unit:"):
        code = fam[5:]
        text = _fraction(value, lang)
        return f"{text} {label(code, lang, value)}".strip() if code else text
    ladder = _LADDERS[fam]
    for code in ladder:
        v = value / UNITS[code].base
        minimum, steps = _FIT[code]
        last = code == ladder[-1]
        if v < minimum and not last:
            continue
        if steps is None:  # ml, g: always fits
            return f"{_decimal(v, lang)} {label(code, lang, v)}"
        if UNITS[code].family in ("spoon", "cup"):
            snapped = _snap(v, steps, 0.005)
            if snapped is not None or last:
                return f"{_fraction(snapped or v, lang)} {label(code, lang, snapped or v)}"
        else:
            snapped = _snap(v, steps, 0.002)
            if snapped is not None:
                return f"{format_qty(Decimal(str(snapped)), lang)} {label(code, lang, snapped)}"
    raise AssertionError("ladder has no catch-all unit")  # pragma: no cover


def amount(qty: Decimal | float | None, code: str, lang: str, factor: float = 1, metric: bool = False) -> str:
    """'2 msk', '1,5 kg', '½ bolli', or just the unit when there's no quantity."""
    if qty is None:
        return label(code, lang) if code else ""
    fam = family(code, metric)
    return present(fam, to_base(float(qty) * factor, code), lang)


def options(lang: str) -> list[tuple[str, str]]:
    """(code, name) for the editor's unit picker."""
    return [(u.code, label(u.code, lang)) for u in UNITS.values()]
