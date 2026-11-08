"""Shopping list (Microsoft To Do). No network: Graph is an httpx MockTransport,
MSAL is a fake app, and the routes get a FakeShoppingList."""
import json
from decimal import Decimal

import httpx
import pytest

from app.config import get_settings
from app.models import MicrosoftAccount
from app.routers import shopping as shop_router
from app.services import recipes as recipe_svc
from app.services.shopping.base import FakeShoppingList, NotConnected, ShoppingError
from app.services.shopping.items import shopping_items, title_name
from app.services.shopping.microsoft import GraphToDo, MicrosoftAuth


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
    monkeypatch.setattr(s, "microsoft_client_id", "client-id")
    monkeypatch.setattr(s, "microsoft_client_secret", "client-secret")
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


# --- Graph --------------------------------------------------------------------

def graph(handler):
    return GraphToDo("AT", transport=httpx.MockTransport(handler))


def test_graph_lists_tasks_and_add():
    posted = []

    def handler(req: httpx.Request):
        assert req.headers["Authorization"] == "Bearer AT"
        path = req.url.path
        if path == "/v1.0/me/todo/lists":
            return httpx.Response(200, json={"value": [
                {"id": "a", "displayName": "Tasks", "wellknownListName": "defaultList"},
                {"id": "b/=", "displayName": "Innkaup", "wellknownListName": "none"},
            ]})
        if req.method == "GET" and path.endswith("/tasks"):
            if "skip" in str(req.url):
                return httpx.Response(200, json={"value": [{"title": "Salt", "status": "notStarted"}]})
            assert req.url.params["$filter"] == "status ne 'completed'"
            return httpx.Response(200, json={
                "value": [{"title": "Mjólk", "status": "notStarted"}, {"title": "Gamalt", "status": "completed"}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/todo/lists/b/tasks?skip=1",
            })
        if req.method == "POST":
            assert req.url.raw_path.startswith(b"/v1.0/me/todo/lists/b%2F%3D/tasks")
            posted.append(json.loads(req.content))
            return httpx.Response(201, json={"id": "t"})
        return httpx.Response(404)

    g = graph(handler)
    lists = g.lists()
    assert [(x.name, x.is_default) for x in lists] == [("Tasks", True), ("Innkaup", False)]
    assert g.open_titles("b") == ["Mjólk", "Salt"]
    g.add_items("b/=", ["Sykur (300 g)"], note="Úr uppskrift: X")
    assert posted == [{"title": "Sykur (300 g)", "body": {"content": "Úr uppskrift: X", "contentType": "text"}}]


def test_graph_errors():
    with pytest.raises(NotConnected):
        graph(lambda req: httpx.Response(401)).lists()
    with pytest.raises(ShoppingError, match="429.*slow down"):
        graph(lambda req: httpx.Response(429, json={"error": {"message": "slow down"}})).lists()


# --- sign-in (MSAL faked) -----------------------------------------------------

ACCOUNT_CACHE = json.dumps({"Account": {"k": {
    "home_account_id": "h.t", "environment": "login.microsoftonline.com", "realm": "common",
    "local_account_id": "l", "username": "me@example.com", "authority_type": "MSSTS"}}})


class FakeMsal:
    def __init__(self, cache):
        self.cache = cache

    def initiate_auth_code_flow(self, scopes, redirect_uri=None, prompt=None, response_mode=None):
        assert response_mode == "form_post"
        assert "offline_access" not in scopes
        return {"auth_uri": f"https://login.example/authorize?redirect_uri={redirect_uri}",
                "state": "s1", "code_verifier": "pkce-verifier-xyz"}

    def acquire_token_by_auth_code_flow(self, flow, params):
        if params.get("state") != flow["state"]:
            raise ValueError("state mismatch")
        self.cache.deserialize(ACCOUNT_CACHE)
        return {"access_token": "AT", "id_token_claims": {"preferred_username": "me@example.com"}}

    def get_accounts(self):
        return list(json.loads(self.cache.serialize()).get("Account", {}).values())

    def acquire_token_silent(self, scopes, account):
        self.cache.has_state_changed = True  # pretend a refresh happened
        return {"access_token": "AT2"}


def auth_for(session, settings, secret=None):
    if secret:
        settings = settings.model_copy(update={"microsoft_client_secret": secret})
    return MicrosoftAuth(settings, session, app_factory=FakeMsal)


def test_sign_in_stores_encrypted_tokens(session, configured):
    auth = auth_for(session, configured)
    url = auth.begin("http://localhost:8000/settings/microsoft/callback")
    assert url.startswith("https://login.example/authorize")
    row = session.get(MicrosoftAccount, 1)
    assert "pkce-verifier-xyz" not in row.auth_flow  # encrypted at rest

    assert auth.finish({"code": "c", "state": "s1"}) == "me@example.com"
    assert auth.connected
    assert row.auth_flow is None and "me@example.com" not in row.token_cache
    before = row.token_cache
    assert auth.token() == "AT2"
    assert row.token_cache != before  # refreshed cache saved

    # A different client secret can't read the stored tokens.
    assert not auth_for(session, configured, secret="rotated").connected
    with pytest.raises(NotConnected):
        auth_for(session, configured, secret="rotated").token()


def test_sign_in_rejects_bad_state_and_errors(session, configured):
    auth = auth_for(session, configured)
    with pytest.raises(ShoppingError, match="No sign-in"):
        auth.finish({"code": "c", "state": "s1"})
    auth.begin("http://localhost/cb")
    with pytest.raises(ShoppingError, match="didn't match"):
        auth.finish({"code": "c", "state": "forged"})
    with pytest.raises(ShoppingError, match="denied"):
        auth.finish({"error": "access_denied", "error_description": "user denied"})
    assert not auth.connected


def test_disconnect(session, configured):
    auth = auth_for(session, configured)
    auth.begin("http://localhost/cb")
    auth.finish({"code": "c", "state": "s1"})
    auth.set_default_list("b", "Innkaup")
    auth.disconnect()
    assert session.get(MicrosoftAccount, 1) is None
    with pytest.raises(NotConnected):
        auth.token()


# --- routes -------------------------------------------------------------------

@pytest.fixture
def shop_client(client, session, configured):
    from app.main import app

    fake = FakeShoppingList({"Tasks": [], "Innkaup": ["mjólk", "Salt (1 tsk)"]})
    auth = auth_for(session, configured)
    app.dependency_overrides[shop_router.get_ms_auth] = lambda: auth
    app.dependency_overrides[shop_router.get_list_factory] = lambda: (lambda: fake)
    client.fake, client.ms = fake, auth
    return client


def test_settings_not_configured(client):
    r = client.get("/settings")
    assert r.status_code == 200 and "MICROSOFT_CLIENT_ID" in r.text
    assert client.post("/settings/microsoft/connect", follow_redirects=False).status_code == 404


def test_settings_connect_flow(shop_client):
    c = shop_client
    r = c.get("/settings")
    assert "Tengjast Microsoft" in r.text
    assert "http://testserver/settings/microsoft/callback" in r.text
    r = c.post("/settings/microsoft/connect", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("https://login.example/authorize")
    r = c.post("/settings/microsoft/callback", data={"code": "c", "state": "s1"}, follow_redirects=False)
    assert r.headers["location"] == "/settings?ok=connected"
    r = c.get("/settings?ok=connected")
    assert "me@example.com" in r.text and "Innkaup" in r.text
    c.post("/settings/microsoft/list", data={"list_id": "Innkaup"})
    assert c.ms.account().list_name == "Innkaup"


def test_callback_error_shows_message(shop_client):
    r = shop_client.get("/settings/microsoft/callback?code=c&state=s1")
    assert "No sign-in in progress" in r.text


def test_read_view_button_only_when_configured(client, session, monkeypatch):
    recipe = make_recipe(session)
    assert "shop-open" not in client.get(f"/recipes/{recipe.id}").text
    s = get_settings()
    monkeypatch.setattr(s, "microsoft_client_id", "x")
    monkeypatch.setattr(s, "microsoft_client_secret", "y")
    assert "shop-open" in client.get(f"/recipes/{recipe.id}").text


def test_dialog_marks_items_already_on_list(shop_client, session):
    recipe = make_recipe(session)
    shop_client.ms.set_default_list("Innkaup", "Innkaup")
    r = shop_client.get(f"/recipes/{recipe.id}/shopping?servings=8")
    assert r.status_code == 200
    assert "Sykur (600 g + 2 msk)" in r.text
    salt = r.text.split("Salt")[0].rsplit("<input", 1)[1]
    assert "checked" not in salt  # already on the list
    sykur = r.text.split("Sykur")[0].rsplit("<input", 1)[1]
    assert "checked" in sykur


def test_add_selected_items(shop_client, session):
    recipe = make_recipe(session)
    items = shopping_items(recipe, "is")
    ids = [ing_id for ing_id, it in items if not it.title.startswith("Salt")]
    r = shop_client.post(f"/recipes/{recipe.id}/shopping",
                         data={"list_id": "Tasks", "servings": "2", "item": ids})
    assert "Bætti 2 atriðum á listann Tasks" in r.text
    assert shop_client.fake.data["Tasks"] == ["Sykur (150 g + 0,5 msk)", "Sveskjur (150 g)"]
    assert shop_client.fake.notes == ["Úr uppskrift: Sveskjuterta"]
    assert shop_client.ms.account().list_id == "Tasks"  # remembered


def test_add_nothing_and_not_connected(shop_client, session):
    from app.main import app

    recipe = make_recipe(session)
    r = shop_client.post(f"/recipes/{recipe.id}/shopping", data={"list_id": "Tasks"})
    assert "Ekkert var valið" in r.text

    def not_connected():
        raise NotConnected("expired")

    app.dependency_overrides[shop_router.get_list_factory] = lambda: not_connected
    r = shop_client.get(f"/recipes/{recipe.id}/shopping")
    assert "Tengdu Microsoft-reikning" in r.text and 'href="/settings"' in r.text
