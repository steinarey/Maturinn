"""Shopping list (Home Assistant to-do). No network: HA is an httpx MockTransport,
and the routes get a FakeShoppingList."""
import json
from decimal import Decimal

import httpx
import pytest

from app.config import get_settings
from app.routers import shopping as shop_router
from app.services import recipes as recipe_svc
from app.services.shopping.base import FakeShoppingList, ShoppingError
from app.services.shopping.items import shopping_items, title_name
from app.services.shopping.homeassistant import HomeAssistantTodo


def make_recipe(session):
    return recipe_svc.save(session, recipe_svc.RecipeIn(
        title="Sveskjuterta", servings=4,
        ingredients=[
            recipe_svc.IngredientIn(quantity=Decimal("200"), unit="g", name="sykur", section="Mauk"),
            recipe_svc.IngredientIn(quantity=Decimal("300"), unit="g", name="sveskjur", section="Mauk"),
            recipe_svc.IngredientIn(quantity=Decimal("100"), unit="g", name="sykur", section="Deig"),
            recipe_svc.IngredientIn(quantity=Decimal("1"), unit="msk", name="sykur", section="Deig"),
            recipe_svc.IngredientIn(name="salt", section="Deig"),
        ],
    ))


@pytest.fixture
def configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "home_assistant_url", "http://ha.test:8123")
    monkeypatch.setattr(s, "home_assistant_token", "TOKEN")
    return s


# --- items --------------------------------------------------------------------

def test_items_merge_same_ingredient_and_scale(session):
    recipe = make_recipe(session)
    titles = [it.title for _, it in shopping_items(recipe, "is")]
    assert titles == ["Sykur (300 g + 1 msk)", "Sveskjur (300 g)", "Salt"]
    scaled = [it.title for _, it in shopping_items(recipe, "is", servings=6)]
    assert scaled == ["Sykur (450 g + 1,5 msk)", "Sveskjur (450 g)", "Salt"]


def test_title_name():
    assert title_name("Sykur (300 g + 1 msk)") == "sykur"
    assert title_name("  Mjólk ") == "mjólk"


# --- Home Assistant API ---------------------------------------------------------

STATES = [
    {"entity_id": "sun.sun", "state": "above_horizon", "attributes": {}},
    {"entity_id": "todo.verkefni", "state": "0", "attributes": {"friendly_name": "Verkefni", "supported_features": 127}},
    {"entity_id": "todo.shopping_list", "state": "2", "attributes": {"friendly_name": "Innkaup", "supported_features": 15}},
]


def ha(handler):
    return HomeAssistantTodo("http://ha.test:8123/", "TOKEN", transport=httpx.MockTransport(handler))


def test_ha_lists_items_and_add():
    calls = []

    def handler(req: httpx.Request):
        assert req.headers["Authorization"] == "Bearer TOKEN"
        if req.url.path == "/api/states":
            return httpx.Response(200, json=STATES)
        body = json.loads(req.content) if req.content else None
        calls.append((req.url.path, req.url.query.decode(), body))
        if req.url.path == "/api/services/todo/get_items":
            return httpx.Response(200, json={"changed_states": [], "service_response": {
                body["entity_id"]: {"items": [{"summary": "Mjólk", "uid": "1", "status": "needs_action"}]}}})
        return httpx.Response(200, json=[])

    h = ha(handler)
    lists = h.lists()
    assert [(x.id, x.name, x.is_default) for x in lists] == [
        ("todo.shopping_list", "Innkaup", True), ("todo.verkefni", "Verkefni", False)]
    assert h.open_titles("todo.shopping_list") == ["Mjólk"]
    assert calls[0] == ("/api/services/todo/get_items", "return_response",
                        {"entity_id": "todo.shopping_list", "status": ["needs_action"]})
    # Shopping List doesn't support descriptions; Local To-do (127) does.
    h.add_items("todo.shopping_list", ["Sykur (300 g)"], note="Úr uppskrift: X")
    h.add_items("todo.verkefni", ["Salt"], note="Úr uppskrift: X")
    assert calls[1:] == [
        ("/api/services/todo/add_item", "", {"entity_id": "todo.shopping_list", "item": "Sykur (300 g)"}),
        ("/api/services/todo/add_item", "", {"entity_id": "todo.verkefni", "item": "Salt",
                                             "description": "Úr uppskrift: X"}),
    ]


def test_ha_errors():
    with pytest.raises(ShoppingError, match="token"):
        ha(lambda req: httpx.Response(401)).lists()
    with pytest.raises(ShoppingError, match="500"):
        ha(lambda req: httpx.Response(500, text="boom")).check()

    def down(req):
        raise httpx.ConnectError("refused")
    with pytest.raises(ShoppingError, match="unreachable"):
        ha(down).lists()


# --- routes -------------------------------------------------------------------

@pytest.fixture
def shop_client(client, configured):
    from app.main import app

    fake = FakeShoppingList({"Tasks": [], "Innkaup": ["mjólk", "Salt (1 tsk)"]})
    app.dependency_overrides[shop_router.get_shopping_list] = lambda: fake
    client.fake = fake
    return client


def test_settings_not_configured(client, session):
    r = client.get("/settings")
    assert r.status_code == 200 and "HOME_ASSISTANT_URL" in r.text
    recipe = make_recipe(session)
    assert client.get(f"/recipes/{recipe.id}/shopping").status_code == 404


def test_settings_shows_lists(configured, client, monkeypatch):
    monkeypatch.setattr(shop_router, "HomeAssistantTodo", lambda url, token: ha(
        lambda req: httpx.Response(200, json=STATES if req.url.path == "/api/states" else {"message": "API running."})))
    r = client.get("/settings")
    assert "todo.shopping_list" in r.text and "Verkefni" in r.text and "sun.sun" not in r.text


def test_settings_shows_error(configured, client, monkeypatch):
    monkeypatch.setattr(shop_router, "HomeAssistantTodo", lambda url, token: ha(lambda req: httpx.Response(401)))
    assert "rejected the access token" in client.get("/settings").text


def test_read_view_button_only_when_configured(client, session, monkeypatch):
    recipe = make_recipe(session)
    assert "shop-open" not in client.get(f"/recipes/{recipe.id}").text
    s = get_settings()
    monkeypatch.setattr(s, "home_assistant_url", "http://ha")
    monkeypatch.setattr(s, "home_assistant_token", "t")
    assert "shop-open" in client.get(f"/recipes/{recipe.id}").text


def test_dialog_marks_items_already_on_list(shop_client, session):
    recipe = make_recipe(session)
    r = shop_client.get(f"/recipes/{recipe.id}/shopping?servings=8&list_id=Innkaup")
    assert r.status_code == 200
    assert "Sykur (600 g + 2 msk)" in r.text
    salt = r.text.split("Salt")[0].rsplit("<input", 1)[1]
    assert "checked" not in salt  # already on the list
    sykur = r.text.split("Sykur")[0].rsplit("<input", 1)[1]
    assert "checked" in sykur


def test_add_selected_items_and_remember_list(shop_client, session):
    recipe = make_recipe(session)
    items = shopping_items(recipe, "is")
    ids = [ing_id for ing_id, it in items if not it.title.startswith("Salt")]
    r = shop_client.post(f"/recipes/{recipe.id}/shopping",
                         data={"list_id": "Innkaup", "servings": "2", "item": ids})
    assert "Bætti 2 atriðum á listann Innkaup" in r.text
    assert shop_client.fake.data["Innkaup"][2:] == ["Sykur (150 g + 0,5 msk)", "Sveskjur (150 g)"]
    assert shop_client.fake.notes == ["Úr uppskrift: Sveskjuterta"]
    assert r.cookies.get("shop_list") == "Innkaup"
    # Next time the dialog opens on that list.
    shop_client.cookies.set("shop_list", "Innkaup")
    r = shop_client.get(f"/recipes/{recipe.id}/shopping")
    assert '<option value="Innkaup" selected' in r.text


def test_add_nothing_and_errors(shop_client, session):
    from app.main import app

    recipe = make_recipe(session)
    r = shop_client.post(f"/recipes/{recipe.id}/shopping", data={"list_id": "Tasks"})
    assert "Ekkert var valið" in r.text

    class Down(FakeShoppingList):
        def lists(self):
            raise ShoppingError("Home Assistant unreachable")

    app.dependency_overrides[shop_router.get_shopping_list] = lambda: Down()
    r = shop_client.get(f"/recipes/{recipe.id}/shopping")
    assert "Home Assistant unreachable" in r.text and 'href="/settings"' in r.text
