"""Turn a recipe's ingredients into shopping list lines."""
from app import units
from app.models import Recipe
from app.services import ingredients as ing_svc
from app.services.shopping.base import ShoppingItem


def title_name(title: str) -> str:
    """Normalized item name of a list line: 'Hveiti (300 g)' -> 'hveiti'."""
    return ing_svc.normalize(title.split(" (", 1)[0])


def shopping_items(recipe: Recipe, lang: str, servings: int | None = None,
                   metric: bool = False) -> list[tuple[int, ShoppingItem]]:
    """One line per ingredient, in recipe order, scaled to `servings`.

    The same ingredient used twice (sugar in the jam and in the dough) becomes one
    line. Amounts are added up within a unit family and shown in the best unit:
    'Sykur (1,3 kg + 2 msk)'. `metric` shows cups as dl/ml. Returns (ingredient id, item) pairs."""
    factor = 1.0
    if servings and recipe.servings:
        factor = servings / recipe.servings

    order: list[int] = []
    # ingredient -> family -> summed amount (ml/g for convertible units), or None when there's no quantity
    amounts: dict[int, dict[str, float | None]] = {}
    for ri in recipe.ingredients:
        ing_id = ri.ingredient_id
        if ing_id not in amounts:
            order.append(ing_id)
            amounts[ing_id] = {}
        fams = amounts[ing_id]
        fam = units.family(ri.unit, metric)
        if ri.quantity is None:
            fams.setdefault(fam, None)
        else:
            fams[fam] = (fams.get(fam) or 0) + units.to_base(float(ri.quantity) * factor, ri.unit)

    by_id = {ri.ingredient_id: ri.ingredient for ri in recipe.ingredients}
    out = []
    for ing_id in order:
        ing = by_id[ing_id]
        name = ing.name_in(lang)
        parts = []
        for fam, value in amounts[ing_id].items():
            if value is not None:
                parts.append(units.present(fam, value, lang))
            elif fam.startswith("unit:") and fam != "unit:":
                parts.append(units.label(fam[5:], lang))
        title = name[:1].upper() + name[1:]
        if parts:
            title += f" ({' + '.join(parts)})"
        out.append((ing_id, ShoppingItem(title=title, names={n.norm for n in ing.names})))
    return out
