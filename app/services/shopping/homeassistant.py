"""Home Assistant to-do lists as the shopping list, via HA's REST API.

Any `todo.*` entity works: the built-in Shopping List, Local To-do, or one
synced from another service. Auth is a long-lived access token (create a
dedicated HA user for it). Adding items fires normal state changes on the
entity, so HA automations can react to them.
"""
import httpx

from app.services.shopping.base import ShoppingError, ShoppingListInfo

SET_DESCRIPTION = 64  # TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
PREFERRED = "todo.shopping_list"  # the built-in Shopping List integration


class HomeAssistantTodo:
    def __init__(self, url: str, token: str, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(
            base_url=url.rstrip("/"), timeout=15, transport=transport,
            headers={"Authorization": f"Bearer {token}"},
        )
        self._features: dict[str, int] = {}

    def _request(self, method: str, url: str, **kw):
        try:
            r = self.client.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise ShoppingError(f"Home Assistant unreachable ({e.__class__.__name__}): {e}") from e
        if r.status_code == 401:
            raise ShoppingError("Home Assistant rejected the access token (401)")
        if r.status_code >= 400:
            raise ShoppingError(f"Home Assistant {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else None

    def check(self) -> None:
        """Raises ShoppingError unless the API answers with this token."""
        self._request("GET", "/api/")

    def lists(self) -> list[ShoppingListInfo]:
        out = []
        for st in self._request("GET", "/api/states"):
            entity = st.get("entity_id", "")
            if not entity.startswith("todo."):
                continue
            attrs = st.get("attributes") or {}
            self._features[entity] = int(attrs.get("supported_features") or 0)
            out.append(ShoppingListInfo(id=entity, name=attrs.get("friendly_name") or entity,
                                        is_default=entity == PREFERRED))
        return sorted(out, key=lambda x: (not x.is_default, x.name.casefold()))

    def open_titles(self, list_id: str) -> list[str]:
        data = self._request("POST", "/api/services/todo/get_items?return_response",
                             json={"entity_id": list_id, "status": ["needs_action"]})
        items = ((data or {}).get("service_response") or {}).get(list_id, {}).get("items", [])
        return [i.get("summary", "") for i in items]

    def add_items(self, list_id: str, titles: list[str], note: str = "") -> None:
        if list_id not in self._features:
            self.lists()
        with_note = bool(note) and bool(self._features.get(list_id, 0) & SET_DESCRIPTION)
        for title in titles:
            body = {"entity_id": list_id, "item": title}
            if with_note:
                body["description"] = note
            self._request("POST", "/api/services/todo/add_item", json=body)
