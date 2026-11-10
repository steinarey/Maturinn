"""Optional recipe category: set in the editor, the API or by import; filter in search."""
import pytest

from app import categories
from app.models import ImportDraft
from app.services import importer
from app.services import recipes as rs
from app.services import search
from app.services.llm.base import ToolCall
from tests.test_recipes import created_id, form


def test_clean():
    assert categories.clean("dinner") == "dinner"
    assert categories.clean(" Kvöldmatur ") == "dinner"
    assert categories.clean("Baking") == "baking"
    assert categories.clean("") is None and categories.clean("brunch") is None


def test_form_sets_category_and_read_view_shows_it(client, session):
    rid = created_id(client.post("/recipes", data=form(category="baking"), follow_redirects=False))
    page = client.get(f"/recipes/{rid}").text
    assert 'href="/?category=baking">Bakkelsi</a>' in page
    assert '<option value="baking" selected>Bakkelsi</option>' in client.get(f"/recipes/{rid}/edit").text
    # Clearing it
    client.post(f"/recipes/{rid}", data=form(category=""))
    assert session.get(rs.Recipe, rid).category is None


def test_search_filters_by_category(client, session):
    rs.save(session, rs.RecipeIn(title="Plokkfiskur", category="dinner"))
    rs.save(session, rs.RecipeIn(title="Kanilsnúðar", category="baking"))
    rs.save(session, rs.RecipeIn(title="Hafragrautur"))
    session.commit()
    assert [r.title for r in search.search(session, category="baking").recipes] == ["Kanilsnúðar"]
    page = client.get("/?category=dinner").text
    assert "Plokkfiskur" in page and "Kanilsnúðar" not in page and "Hafragrautur" not in page
    assert '<option value="dinner" selected>Kvöldmatur</option>' in page
    assert "Kanilsnúðar" in client.get("/?category=nonsense").text  # unknown = no filter
    r = client.get("/api/recipes", params={"category": "Bakkelsi"}).json()
    assert [x["title"] for x in r["recipes"]] == ["Kanilsnúðar"] and r["recipes"][0]["category"] == "baking"


def test_api_rejects_unknown_category(client):
    r = client.post("/api/recipes", json={"title": "X", "category": "brunch"})
    assert r.status_code == 422
    r = client.post("/api/recipes", json={"title": "X", "category": "Snarl"})
    assert r.status_code == 201 and r.json()["category"] == "snack"


@pytest.mark.parametrize("given,stored", [("dessert", "dessert"), ("brunch", None), (None, None)])
def test_import_sets_category(session, given, stored):
    row = ImportDraft(kind="text", status="extracting", source_text="x")
    session.add(row)
    session.flush()
    b = importer.DraftBuilder(session, row)
    b(ToolCall(id="1", name="set_details", args={"title": "Ís", "language": "is", "category": given}))
    assert b.state["category"] == stored
