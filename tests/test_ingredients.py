import pytest

from app.models import Ingredient, RecipeIngredient
from app.services import ingredients as ing
from app.services import recipes as recipes


def test_normalize_keeps_icelandic_letters():
    assert ing.normalize("  Þorskur  ÐÆÖ Á. ") == "þorskur ðæö á"
    assert ing.normalize("Kjúklingabringa,") == "kjúklingabringa"


@pytest.mark.parametrize("name,expected", [
    ("chicken breasts", "chicken breast"),
    ("berries", "berry"),
    ("tomatoes", "tomato"),
    ("peaches", "peach"),
    ("leaves", "leaf"),
])
def test_candidates_singularize_last_word(name, expected):
    assert expected in ing.candidates(name)


@pytest.mark.parametrize("word", ["glass", "asparagus", "couscous"])
def test_candidates_leave_non_plurals_alone(word):
    assert ing.candidates(word) == [word]


@pytest.mark.parametrize("a,b,same", [
    ("kjúklingabringa", "kjúklingabringur", True),
    ("laukur", "laukar", True),
    ("mjólk", "mjólkur", True),
    ("salt", "salat", False),
    ("pear", "pearl", False),
    ("rjómi", "rjómaostur", False),
    ("egg", "eggaldin", False),
])
def test_is_inflection(a, b, same):
    assert ing.is_inflection(a, b) is same


def test_resolve_reuses_plural_and_case_variants(session):
    a, created = ing.resolve(session, "chicken breast", "en")
    assert created
    b, created = ing.resolve(session, "Chicken Breasts", "en")
    assert not created and b.id == a.id


def test_resolve_matches_icelandic_inflection(session):
    a, _ = ing.resolve(session, "kjúklingabringa", "is")
    b, created = ing.resolve(session, "kjúklingabringur", "is")
    assert not created and b.id == a.id


def test_resolve_does_not_merge_different_words(session):
    salt, _ = ing.resolve(session, "salt", "is")
    salat, created = ing.resolve(session, "salat", "is")
    assert created and salat.id != salt.id


def test_alias_and_other_language_resolve_to_same_row(session):
    chicken, _ = ing.resolve(session, "kjúklingabringa", "is")
    ing.set_names(session, chicken, "en", "chicken breast", ["chicken fillet"])
    for name in ["chicken fillet", "chicken breasts", "Kjúklingabringa"]:
        found, created = ing.resolve(session, name, "en")
        assert not created and found.id == chicken.id, name
    assert chicken.name_in("en") == "chicken breast"
    assert chicken.name_in("is") == "kjúklingabringa"


def test_set_names_rejects_name_owned_by_another_ingredient(session):
    a, _ = ing.resolve(session, "garlic", "en")
    b, _ = ing.resolve(session, "onion", "en")
    with pytest.raises(ing.NameConflict):
        ing.set_names(session, b, "en", "onion", ["garlic"])


def test_merge_moves_recipe_rows_and_names(session):
    recipes.save(session, recipes.RecipeIn(title="A", original_lang="en", ingredients=[
        recipes.IngredientIn(name="scallion"),
    ]))
    scallion = ing.find(session, "scallion")
    spring, _ = ing.resolve(session, "spring onion", "en")
    ing.merge(session, scallion, spring)
    session.expire_all()
    assert session.get(Ingredient, scallion.id) is None
    assert ing.find(session, "scallion").id == spring.id
    rows = session.query(RecipeIngredient).filter_by(ingredient_id=spring.id).count()
    assert rows == 1


def test_with_descendants_follows_groups(session):
    nuts, _ = ing.resolve(session, "nuts", "en")
    almond, _ = ing.resolve(session, "almond", "en")
    marcona, _ = ing.resolve(session, "marcona almond", "en")
    almond.parent_id = nuts.id
    marcona.parent_id = almond.id
    session.flush()
    assert ing.with_descendants(session, {nuts.id}) == {nuts.id, almond.id, marcona.id}


def test_suggest_finds_similar_names(session):
    ing.resolve(session, "spaghetti", "en")
    names = [s.name for s in ing.suggest(session, "spagetti")]
    assert "spaghetti" in names
