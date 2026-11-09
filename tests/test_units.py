"""Units: stored as codes, imperial converted on save, shown in the friendliest unit."""
from decimal import Decimal as D

import pytest

from app import units
from app.services import recipes as recipe_svc


@pytest.mark.parametrize("raw,code", [
    ("tsk.", "tsp"), ("Teaspoons", "tsp"), ("t", "tsp"), ("T", "tbsp"), ("msk", "tbsp"),
    ("bollar", "cup"), ("cups", "cup"), ("Stk.", "pc"), ("hnífsoddur", "pinch"), ("dósir", "can"),
    ("desilítrar", "dl"), ("kg", "kg"),
])
def test_aliases(raw, code):
    assert units.canonical(D(1), raw) == (D(1), code)


@pytest.mark.parametrize("qty,raw,expected", [
    ("2", "oz", (D(57), "g")), ("1", "lb", (D(454), "g")), ("2", "fl. oz", (D(59), "ml")),
    ("1", "quart", (D(946), "ml")), ("1", "stick", (D(113), "g")), ("2", "cl", (D(20), "ml")),
])
def test_imperial_converted(qty, raw, expected):
    assert units.canonical(D(qty), raw) == expected


def test_unknown_kept():
    assert units.canonical(D(2), "grein") == (D(2), "grein")
    assert units.amount(D(2), "grein", "is") == "2 grein"
    assert units.canonical(None, "") == (None, "")


@pytest.mark.parametrize("qty,code,factor,expected", [
    ("3", "tsp", 1, "1 msk"),
    ("4", "tsp", 1, "4 tsk"),          # not 1⅓ msk
    ("2", "tsp", 3, "2 msk"),
    ("1", "tbsp", 1 / 3, "1 tsk"),
    ("1", "tbsp", 0.5, "½ msk"),
    ("6", "tbsp", 1, "6 msk"),         # 0,9 dl isn't easier
    ("10", "tbsp", 1, "1,5 dl"),
    ("10", "dl", 1, "1 l"),
    ("250", "ml", 1, "2,5 dl"),
    ("333", "ml", 1, "333 ml"),
    ("1500", "g", 1, "1,5 kg"),
    ("1250", "g", 1, "1,25 kg"),
    ("1", "cup", 2, "2 bollar"),
    ("0.125", "cup", 1, "2 msk"),
    ("21", "cup", 1, "21 bolli"),
    ("0.5", "", 1, "½"),
    ("1", "can", 2, "2 dósir"),
])
def test_amount(qty, code, factor, expected):
    assert units.amount(D(qty), code, "is", factor=factor) == expected


def test_amount_english_and_metric_cups():
    assert units.amount(D("1.5"), "cup", "en") == "1½ cups"
    assert units.amount(D(1), "cup", "is", metric=True) == "2,4 dl"
    assert units.amount(D("0.75"), "cup", "en", metric=True) == "1.8 dl"
    assert units.amount(None, "pinch", "is") == "klípa"


def test_saved_as_codes_and_shown_translated(session, client):
    r = recipe_svc.save(session, recipe_svc.RecipeIn(title="Pönnukökur", servings=4, ingredients=[
        recipe_svc.IngredientIn(quantity=D(2), unit="bollar", name="hveiti"),
        recipe_svc.IngredientIn(quantity=D(2), unit="tsk.", name="sykur"),
        recipe_svc.IngredientIn(quantity=D(8), unit="oz", name="smjör"),
    ]))
    session.commit()
    assert [(i.quantity, i.unit) for i in r.ingredients] == [(D(2), "cup"), (D(2), "tsp"), (D(227), "g")]
    page = client.get(f"/recipes/{r.id}").text
    assert "2 bollar" in page and 'id="metric"' in page
    a = client.get(f"/recipes/{r.id}/amounts?servings=6").json()
    assert list(a.values()) == ["3 bollar", "1 msk", "340 g"]
    a = client.get(f"/recipes/{r.id}/amounts?servings=4&metric=true").json()
    assert list(a.values())[0] == "4,8 dl"
    client.cookies.set("lang", "en")
    assert "2 cups" in client.get(f"/recipes/{r.id}").text


def test_no_metric_switch_without_cups(session, client):
    r = recipe_svc.save(session, recipe_svc.RecipeIn(title="X", ingredients=[
        recipe_svc.IngredientIn(quantity=D(1), unit="dl", name="mjólk")]))
    session.commit()
    assert 'id="metric"' not in client.get(f"/recipes/{r.id}").text


def test_editor_unit_picker(session, client):
    r = recipe_svc.save(session, recipe_svc.RecipeIn(title="X", ingredients=[
        recipe_svc.IngredientIn(quantity=D(1), unit="msk", name="olía"),
        recipe_svc.IngredientIn(quantity=D(1), unit="grein", name="rósmarín")]))
    session.commit()
    page = client.get(f"/recipes/{r.id}/edit").text
    assert '<option value="tbsp" selected>msk</option>' in page
    assert '<option value="grein" selected>grein ?</option>' in page


def test_shopping_adds_up_within_family(session):
    from app.services.shopping.items import shopping_items
    r = recipe_svc.save(session, recipe_svc.RecipeIn(title="X", servings=2, ingredients=[
        recipe_svc.IngredientIn(quantity=D(1), unit="kg", name="hveiti", section="A"),
        recipe_svc.IngredientIn(quantity=D(300), unit="g", name="hveiti", section="B"),
        recipe_svc.IngredientIn(quantity=D(2), unit="tsk", name="salt", section="A"),
        recipe_svc.IngredientIn(quantity=D(1), unit="tsk", name="salt", section="B"),
        recipe_svc.IngredientIn(quantity=D(1), unit="bolli", name="mjólk"),
    ]))
    assert [it.title for _, it in shopping_items(r, "is")] == ["Hveiti (1,3 kg)", "Salt (1 msk)", "Mjólk (1 bolli)"]
    assert [it.title for _, it in shopping_items(r, "is", metric=True)][2] == "Mjólk (2,4 dl)"
