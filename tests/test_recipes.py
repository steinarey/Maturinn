"""CRUD through the HTML forms and the JSON API, plus photo upload."""
import io
from decimal import Decimal

from PIL import Image

from app.config import get_settings
from app.services import recipes as rs


def form(**overrides):
    data = {
        "title": "Pönnukökur", "description": "Sunnudagsmorgunn", "servings": "4",
        "original_lang": "is", "source_url": "", "tags": "morgunmatur, sætt",
        "ing_id": ["", ""], "ing_qty": ["2,5", "1 1/2"], "ing_unit": ["dl", "msk"],
        "ing_name": ["hveiti", "sykur"], "ing_note": ["", "má sleppa"],
        "item_id": [""], "item_name": ["pönnukökupanna"],
        "step_key": ["k1", "k2"], "step_id": ["", ""],
        "step_text": ["Hrærið saman.", "Steikið á heitri pönnu."],
    }
    data.update(overrides)
    return data


def created_id(response) -> int:
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[1])


def test_create_via_form_and_read_view(client, session):
    recipe_id = created_id(client.post("/recipes", data=form(), follow_redirects=False))
    recipe = rs.load(session, recipe_id)
    assert [i.quantity for i in recipe.ingredients] == [Decimal("2.5"), Decimal("1.5")]
    assert [i.ingredient.name_in("is") for i in recipe.ingredients] == ["hveiti", "sykur"]
    assert [s.text for s in recipe.steps] == ["Hrærið saman.", "Steikið á heitri pönnu."]
    assert [i.name for i in recipe.items] == ["pönnukökupanna"]

    page = client.get(f"/recipes/{recipe_id}").text
    # Read order: title, ingredients, you'll need, steps.
    order = [page.index(s) for s in ["<h1>Pönnukökur", "hveiti", "pönnukökupanna", "Hrærið saman"]]
    assert order == sorted(order)
    assert "2,5 dl" in page  # Icelandic decimal comma

    client.cookies.set("lang", "en")
    assert "2.5 dl" in client.get(f"/recipes/{recipe_id}").text


def test_edit_keeps_child_ids(client, session):
    recipe_id = created_id(client.post("/recipes", data=form(), follow_redirects=False))
    recipe = rs.load(session, recipe_id)
    ing_ids = [str(i.id) for i in recipe.ingredients]
    step_ids = [str(s.id) for s in recipe.steps]

    # Reorder steps, change one ingredient quantity.
    r = client.post(f"/recipes/{recipe_id}", data=form(
        ing_id=ing_ids, ing_qty=["3", "1 1/2"],
        step_key=["k2", "k1"], step_id=[step_ids[1], step_ids[0]],
        step_text=["Steikið á heitri pönnu.", "Hrærið saman."],
    ), follow_redirects=False)
    assert created_id(r) == recipe_id
    session.expire_all()
    recipe = rs.load(session, recipe_id)
    assert [str(i.id) for i in recipe.ingredients] == ing_ids
    assert recipe.ingredients[0].quantity == Decimal("3")
    assert [str(s.id) for s in recipe.steps] == [step_ids[1], step_ids[0]]


def test_changing_ingredient_name_relinks_row(client, session):
    recipe_id = created_id(client.post("/recipes", data=form(), follow_redirects=False))
    recipe = rs.load(session, recipe_id)
    ing_ids = [str(i.id) for i in recipe.ingredients]
    client.post(f"/recipes/{recipe_id}", data=form(ing_id=ing_ids, ing_name=["hveiti", "púðursykur"]))
    session.expire_all()
    recipe = rs.load(session, recipe_id)
    assert recipe.ingredients[1].ingredient.name_in("is") == "púðursykur"


def test_bad_quantity_rerenders_with_error(client):
    r = client.post("/recipes", data=form(ing_qty=["tvær", "1"]))
    assert r.status_code == 422
    assert "Magn skilst ekki" in r.text
    assert 'value="Pönnukökur"' in r.text  # input kept


def test_missing_title_rejected(client):
    r = client.post("/recipes", data=form(title="  "))
    assert r.status_code == 422
    assert "Heiti vantar" in r.text


def test_delete(client):
    recipe_id = created_id(client.post("/recipes", data=form(), follow_redirects=False))
    assert client.post(f"/recipes/{recipe_id}/delete", follow_redirects=False).status_code == 303
    assert client.get(f"/recipes/{recipe_id}").status_code == 404


def test_pages_render(client):
    recipe_id = created_id(client.post("/recipes", data=form(), follow_redirects=False))
    for url in ["/", "/recipes/new", f"/recipes/{recipe_id}/edit", "/ingredients",
                "/fragments/ingredient-row", "/fragments/step-row", "/fragments/item-row",
                "/fragments/ingredient-check?ing_name=hveiti", "/fragments/ingredient-options?ing_name=hv"]:
        assert client.get(url).status_code == 200, url
    assert "hveiti" in client.get("/ingredients").text
    assert "✓" in client.get("/fragments/ingredient-check?ing_name=Hveiti").text


def test_ingredient_admin_rename_and_group(client, session):
    from app.services import ingredients as ing
    created_id(client.post("/recipes", data=form(), follow_redirects=False))
    flour = ing.find(session, "hveiti")
    group, _ = ing.resolve(session, "mjöl", "is")
    session.flush()
    r = client.post(f"/ingredients/{flour.id}", data={
        "name_is": "hveiti", "aliases_is": "hveitimjöl", "name_en": "flour", "aliases_en": "plain flour",
        "parent_id": str(group.id), "food_id": "",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert ing.find(session, "plain flour").id == flour.id
    assert client.get("/api/recipes", params={"q": "flour"}).json()["recipes"]
    assert client.get("/api/recipes", params={"without": "mjöl"}).json()["recipes"] == []


def test_api_roundtrip(client):
    payload = {
        "title": "Chicken curry", "original_lang": "en", "servings": 4, "tags": ["dinner"],
        "ingredients": [{"quantity": "4", "unit": "pieces", "name": "chicken breast"}],
        "items": [{"name": "cast iron pan"}],
        "steps": [{"text": "Brown the chicken."}, {"text": "Add sauce."}],
    }
    r = client.post("/api/recipes", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    rid, step_id = body["id"], body["steps"][0]["id"]
    assert body["ingredients"][0]["name"] == "chicken breast"

    body["steps"][0]["text"] = "Brown the chicken well."
    r = client.put(f"/api/recipes/{rid}", json=body)
    assert r.status_code == 200
    assert r.json()["steps"][0] == {"id": step_id, "text": "Brown the chicken well.", "photos": []}

    found = client.get("/api/recipes", params={"has": "chicken breasts"}).json()
    assert [x["id"] for x in found["recipes"]] == [rid]

    assert client.delete(f"/api/recipes/{rid}").status_code == 204
    assert client.get(f"/api/recipes/{rid}").status_code == 404


def test_photo_upload_and_attach(client, session):
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), "orange").save(buf, "PNG")
    r = client.post("/fragments/photo", data={"key": "k1"},
                    files=[("files", ("a.png", buf.getvalue(), "image/png"))])
    assert r.status_code == 200
    path = r.text.split('name="photo_path_k1" value="')[1].split('"')[0]
    full = get_settings().photos_dir / path
    assert full.exists() and full.with_name(full.stem + "_t.jpg").exists()
    assert max(Image.open(full).size) == 2000

    recipe_id = created_id(client.post(
        "/recipes", data=form(**{"photo_path_k1": [path], "photo_caption_k1": ["deig"]}),
        follow_redirects=False))
    recipe = rs.load(session, recipe_id)
    assert [(p.path, p.caption) for p in recipe.steps[0].photos] == [(path, "deig")]
    assert client.get(f"/photos/{path}").status_code == 200


def test_upload_rejects_non_image(client):
    r = client.post("/fragments/photo", data={"key": "k1"},
                    files=[("files", ("a.txt", b"not an image", "text/plain"))])
    assert r.status_code == 422


def test_list_card_without_photo_is_a_title_card(client, session):
    from app.services import recipes as rs
    rs.save(session, rs.RecipeIn(title="Plokkfiskur", description="Gamli góði, með [rúgbrauði](recipe:999).",
                                 tags=["fiskur"]))
    session.commit()
    page = client.get("/").text
    card = page.split('class="card text')[1].split("</li>\n  \n")[0]
    assert "Plokkfiskur" in card and "Gamli góði, með rúgbrauði." in card and "fiskur" in card
    assert "thumb" not in card
