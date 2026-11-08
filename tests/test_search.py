"""Search across both languages, Icelandic inflection, and ingredient filters."""
import pytest

from app.services import ingredients as ing
from app.services import recipes as rs
from app.services.search import search, stem_prefix


def I(name, qty=None, unit=""):
    return rs.IngredientIn(name=name, quantity=qty, unit=unit)


@pytest.fixture
def data(session):
    # Canonical names and groups first, so recipes link to them.
    chicken, _ = ing.resolve(session, "kjúklingabringa", "is")
    ing.set_names(session, chicken, "en", "chicken breast", ["chicken fillet"])
    nuts, _ = ing.resolve(session, "hnetur", "is")
    ing.set_names(session, nuts, "en", "nuts", [])
    cashew, _ = ing.resolve(session, "kasjúhnetur", "is")
    almond, _ = ing.resolve(session, "almonds", "en")
    cashew.parent_id = nuts.id
    almond.parent_id = nuts.id
    session.flush()

    curry = rs.save(session, rs.RecipeIn(
        title="Kjúklingur í karrý", original_lang="is", tags=["kvöldmatur"],
        ingredients=[I("kjúklingabringur", 4, "stk"), I("laukur", 1), I("kasjúhnetur", 50, "g")]))
    pasta = rs.save(session, rs.RecipeIn(
        title="Garlic pasta", original_lang="en", tags=["quick"],
        ingredients=[I("spaghetti", 400, "g"), I("garlic", 4, "cloves"), I("almonds", 30, "g")]))
    salad = rs.save(session, rs.RecipeIn(
        title="Laxasalat", original_lang="is",
        ingredients=[I("lax", 300, "g"), I("sítróna", 1), I("klettasalat")]))
    session.flush()
    return {"curry": curry.id, "pasta": pasta.id, "salad": salad.id}


def ids(result):
    return {r.id for r in result.recipes}


def test_stem_prefix():
    assert stem_prefix("kjúklingabringur") == "kjúklingabring"
    assert stem_prefix("salat") == "sala"
    assert stem_prefix("lax") == "lax"


def test_empty_query_lists_everything(session, data):
    assert ids(search(session)) == set(data.values())


@pytest.mark.parametrize("q,key", [
    ("kjúklingabringa", "curry"),     # canonical name
    ("kjúklingabringur", "curry"),    # plural form, as entered
    ("kjúklingabringum", "curry"),    # dative plural
    ("chicken breasts", "curry"),     # English name of the same ingredient
    ("chicken fillet", "curry"),      # English alias
    ("karrý", "curry"),               # title word
    ("kvöldmatur", "curry"),          # tag
    ("laukar", "curry"),              # other inflection of laukur
    ("garlic", "pasta"),
    ("pasta", "pasta"),
    ("spagetti", "pasta"),            # typo, via trigram
    ("laxasalati", "salad"),          # dative of laxasalat
    ("lax", "salad"),
])
def test_query_finds(session, data, q, key):
    assert data[key] in ids(search(session, q)), q


def test_words_are_anded(session, data):
    assert ids(search(session, "kjúklingur garlic")) == set()
    assert ids(search(session, "garlic pasta")) == {data["pasta"]}


def test_short_word_does_not_fuzzy_match_other_word(session, data):
    assert data["salad"] not in ids(search(session, "salt"))


def test_has_ingredient_any_language(session, data):
    assert ids(search(session, has=["kjúklingabringa"])) == {data["curry"]}
    assert ids(search(session, has=["chicken breasts"])) == {data["curry"]}
    assert ids(search(session, has=["chicken"])) == {data["curry"]}  # word inside "chicken breast"


def test_has_multiple_ingredients_requires_all(session, data):
    assert ids(search(session, has=["spaghetti", "garlic"])) == {data["pasta"]}
    assert ids(search(session, has=["spaghetti", "lax"])) == set()


def test_without_group_excludes_members(session, data):
    assert ids(search(session, without=["hnetur"])) == {data["salad"]}
    assert ids(search(session, without=["nuts"])) == {data["salad"]}


def test_without_single_member(session, data):
    assert ids(search(session, without=["kasjúhnetur"])) == {data["pasta"], data["salad"]}


def test_query_and_filters_combine(session, data):
    assert ids(search(session, "pasta", without=["nuts"])) == set()
    assert ids(search(session, "lax", has=["sítróna"])) == {data["salad"]}


def test_unknown_filter_ingredient_is_reported(session, data):
    result = search(session, has=["drekaávöxtur"])
    assert result.recipes == [] and result.unknown == ["drekaávöxtur"]
    result = search(session, without=["drekaávöxtur"])
    assert ids(result) == set(data.values()) and result.unknown == ["drekaávöxtur"]


def test_renaming_ingredient_updates_search(session, data):
    from app.services.search import reindex_ingredient
    lax = ing.find(session, "lax")
    ing.set_names(session, lax, "en", "salmon", [])
    reindex_ingredient(session, lax.id)
    assert ids(search(session, "salmon")) == {data["salad"]}
