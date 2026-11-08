"""Turn a recipe's ingredients into shopping list lines."""
from decimal import Decimal

from app.i18n import format_qty
from app.models import Recipe
from app.services import ingredients as ing_svc
from app.services.shopping.base import ShoppingItem


def title_name(title: str) -> str:
    """Normalized item name of a list line: 'Hveiti (300 g)' -> 'hveiti'."""
    return ing_svc.normalize(title.split(" (", 1)[0])


def shopping_items(recipe: Recipe, lang: str, servings: int | None = None) -> list[tuple[int, ShoppingItem]]:
    """One line per ingredient, in recipe order, scaled to `servings`.

    The same ingredient used twice (sugar in the jam and in the dough) becomes one
    line, with quantities summed per unit: 'Sykur (300 g + 2 msk)'.
    Returns (ingredient id, item) pairs."""
    factor = Decimal(1)
    if servings and recipe.servings:
        factor = Decimal(servings) / Decimal(recipe.servings)

    order: list[int] = []
    amounts: dict[int, dict[str, Decimal | None]] = {}
    for ri in recipe.ingredients:
        ing_id = ri.ingredient_id
        if ing_id not in amounts:
            order.append(ing_id)
            amounts[ing_id] = {}
        units = amounts[ing_id]
        unit = ri.unit.strip()
        if ri.quantity is None:
            units.setdefault(unit, None)
        else:
            units[unit] = (units.get(unit) or 0) + ri.quantity * factor

    by_id = {ri.ingredient_id: ri.ingredient for ri in recipe.ingredients}
    out = []
    for ing_id in order:
        ing = by_id[ing_id]
        name = ing.name_in(lang)
        parts = []
        for unit, q in amounts[ing_id].items():
            if q is not None:
                parts.append(f"{format_qty(q, lang)} {unit}".strip())
            elif unit:
                parts.append(unit)
        title = name[:1].upper() + name[1:]
        if parts:
            title += f" ({' + '.join(parts)})"
        out.append((ing_id, ShoppingItem(title=title, names={n.norm for n in ing.names})))
    return out
