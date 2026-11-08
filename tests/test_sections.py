"""Ingredient sections: form round-trip, read view headings, API, import tool."""
from app.models import ImportDraft
from app.services import importer
from app.services import recipes as rs
from app.services.llm.fake import FakeLLM


def form_with_sections():
    # DOM order: heading, 2 ingredients, heading, 2 ingredients.
    return {
        "title": "Sveskjuterta", "description": "", "servings": "", "original_lang": "is",
        "source_url": "", "tags": "",
        "row_kind": ["sec", "ing", "ing", "sec", "ing", "ing"],
        "sec_name": ["Sveskjumauk", "Deig"],
        "ing_id": ["", "", "", ""], "ing_qty": ["750", "250", "1250", "500"],
        "ing_unit": ["g", "g", "g", "g"], "ing_name": ["sveskjur", "sykur", "hveiti", "sykur"],
        "ing_note": ["", "", "", ""],
        "step_key": ["a"], "step_id": [""], "step_text": ["Bakið."],
    }


def created_id(r):
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[1])


def test_form_saves_sections_and_edit_restores_headings(client, session):
    rid = created_id(client.post("/recipes", data=form_with_sections(), follow_redirects=False))
    recipe = rs.load(session, rid)
    assert [(r.section, r.ingredient.name_in("is")) for r in recipe.ingredients] == [
        ("Sveskjumauk", "sveskjur"), ("Sveskjumauk", "sykur"), ("Deig", "hveiti"), ("Deig", "sykur")]
    # Both sugars are the same canonical ingredient.
    assert recipe.ingredients[1].ingredient_id == recipe.ingredients[3].ingredient_id

    edit = client.get(f"/recipes/{rid}/edit").text
    assert edit.count('name="row_kind" value="sec"') == 2
    assert edit.index('value="Sveskjumauk"') < edit.index('value="sveskjur"') < edit.index('value="Deig"') \
        < edit.index('value="hveiti"')


def test_read_view_groups_under_headings(client):
    rid = created_id(client.post("/recipes", data=form_with_sections(), follow_redirects=False))
    page = client.get(f"/recipes/{rid}").text
    assert page.count("<h3>Sveskjumauk</h3>") == 1 and page.count("<h3>Deig</h3>") == 1
    assert page.index("<h3>Sveskjumauk</h3>") < page.index("sveskjur") < page.index("<h3>Deig</h3>") \
        < page.index("hveiti")


def test_rows_before_first_heading_have_no_section(client, session):
    data = form_with_sections()
    data.update(row_kind=["ing", "sec", "ing", "ing", "ing"], sec_name=["Deig"])
    recipe = rs.load(session, created_id(client.post("/recipes", data=data, follow_redirects=False)))
    assert [r.section for r in recipe.ingredients] == ["", "Deig", "Deig", "Deig"]


def test_moving_heading_regroups(client, session):
    rid = created_id(client.post("/recipes", data=form_with_sections(), follow_redirects=False))
    ids = [str(r.id) for r in rs.load(session, rid).ingredients]
    data = form_with_sections()
    # Drag the "Deig" heading up one row: the first sugar now belongs to Deig.
    data.update(ing_id=ids, row_kind=["sec", "ing", "sec", "ing", "ing", "ing"])
    client.post(f"/recipes/{rid}", data=data)
    session.expire_all()
    assert [r.section for r in rs.load(session, rid).ingredients] == ["Sveskjumauk", "Deig", "Deig", "Deig"]


def test_section_fragment(client):
    r = client.get("/fragments/section-row")
    assert r.status_code == 200 and 'name="sec_name"' in r.text


def test_api_sections_roundtrip(client):
    payload = {"title": "Pie", "original_lang": "en", "ingredients": [
        {"name": "flour", "quantity": "200", "unit": "g", "section": "Crust"},
        {"name": "apple", "quantity": "4", "section": "Filling"}]}
    body = client.post("/api/recipes", json=payload).json()
    assert [i["section"] for i in body["ingredients"]] == ["Crust", "Filling"]


def test_import_start_section(session):
    row = ImportDraft(kind="text", source_text="x", status="extracting", events=[])
    session.add(row)
    session.flush()
    importer.process(session, row, FakeLLM([
        ("set_details", {"title": "Sveskjuterta", "language": "is"}),
        ("start_section", {"name": "Sveskjumauk"}),
        ("add_ingredient", {"name": "sveskjur", "quantity": 750, "unit": "g"}),
        ("start_section", {"name": "Deig"}),
        ("add_ingredient", {"name": "hveiti", "quantity": 1250, "unit": "g"}),
        ("add_step", {"text": "Bakið."}),
    ]))
    assert row.status == "ready"
    assert [(i["section"], i["name"]) for i in row.draft["ingredients"]] == [
        ("Sveskjumauk", "sveskjur"), ("Deig", "hveiti")]
    assert [e["name"] for e in row.events if e["t"] == "section"] == ["Sveskjumauk", "Deig"]
    # Draft renders in the review form with headings.
    from app.routers.pages import ingredient_rows
    rows = ingredient_rows(rs.RecipeIn(**row.draft).ingredients, "is")
    assert [r["kind"] for r in rows] == ["sec", "ing", "sec", "ing"]
