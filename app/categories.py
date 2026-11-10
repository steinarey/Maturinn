"""Recipe categories: a fixed list, stored as codes and shown translated.

Adding one is a code change only (no migration): append it here with its names.
A recipe has at most one category; it's optional."""

CATEGORIES: dict[str, dict[str, str]] = {
    "breakfast": {"is": "Morgunmatur", "en": "Breakfast"},
    "dinner": {"is": "Kvöldmatur", "en": "Dinner"},
    "side": {"is": "Meðlæti", "en": "Side dish"},
    "snack": {"is": "Snarl", "en": "Snack"},
    "baking": {"is": "Bakkelsi", "en": "Baking"},
    "dessert": {"is": "Eftirréttur", "en": "Dessert"},
    "drink": {"is": "Drykkur", "en": "Drink"},
    "basics": {"is": "Grunnuppskriftir", "en": "Basics"},
}


def label(code: str | None, lang: str) -> str:
    names = CATEGORIES.get(code or "")
    return (names.get(lang) or names["en"]) if names else ""


def options(lang: str) -> list[tuple[str, str]]:
    return [(code, label(code, lang)) for code in CATEGORIES]


def clean(value: str | None) -> str | None:
    """A valid code or None. Also accepts a name in either language ('Kvöldmatur')."""
    v = (value or "").strip().casefold()
    if not v:
        return None
    for code, names in CATEGORIES.items():
        if v == code or v in (n.casefold() for n in names.values()):
            return code
    return None
