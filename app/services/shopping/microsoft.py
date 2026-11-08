"""Microsoft To Do as the shopping list, through Microsoft Graph.

Sign-in is the OAuth authorization code flow (with PKCE) via MSAL, as a
confidential client (MICROSOFT_CLIENT_ID + MICROSOFT_CLIENT_SECRET). One
household, one connected account: MSAL's token cache (holding the refresh
token) is stored in the `microsoft_account` row, encrypted with a key derived
from the client secret. Access tokens are refreshed silently; if the refresh
token has expired (about 90 days unused for personal accounts) the user
connects again.
"""
import base64
import hashlib
import json
from collections.abc import Callable
from urllib.parse import quote

import httpx
import msal
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import MicrosoftAccount
from app.services.shopping.base import NotConnected, ShoppingError, ShoppingListInfo

GRAPH = "https://graph.microsoft.com/v1.0"


def _fernet(secret: str) -> Fernet:
    digest = hashlib.sha256(b"maturinn:microsoft-account:" + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class MicrosoftAuth:
    """Connects the household's Microsoft account and hands out access tokens."""

    def __init__(self, settings: Settings, session: Session,
                 app_factory: Callable[[msal.SerializableTokenCache], object] | None = None):
        self.settings = settings
        self.session = session
        self._fernet = _fernet(settings.microsoft_client_secret or "")
        self._app_factory = app_factory or self._msal_app

    def _msal_app(self, cache: msal.SerializableTokenCache):
        s = self.settings
        try:
            return msal.ConfidentialClientApplication(
                s.microsoft_client_id, client_credential=s.microsoft_client_secret,
                authority=s.microsoft_authority, token_cache=cache, timeout=15,
            )
        except Exception as e:  # authority discovery is a network call
            raise ShoppingError(f"Microsoft sign-in unavailable: {e}") from e

    # --- stored state ---------------------------------------------------------

    def account(self) -> MicrosoftAccount | None:
        return self.session.get(MicrosoftAccount, 1)

    def _row(self) -> MicrosoftAccount:
        row = self.account()
        if row is None:
            row = MicrosoftAccount(id=1)
            self.session.add(row)
        return row

    def _encrypt(self, text: str) -> str:
        return self._fernet.encrypt(text.encode()).decode()

    def _decrypt(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:  # client secret changed: treat as not connected
            return None

    def _load_cache(self, row: MicrosoftAccount | None) -> msal.SerializableTokenCache:
        cache = msal.SerializableTokenCache()
        data = self._decrypt(row.token_cache) if row else None
        if data:
            cache.deserialize(data)
        return cache

    @property
    def connected(self) -> bool:
        row = self.account()
        return bool(row and row.username and self._decrypt(row.token_cache))

    # --- sign-in --------------------------------------------------------------

    def begin(self, redirect_uri: str) -> str:
        """Start a sign-in. Returns the Microsoft URL to send the browser to."""
        app = self._app_factory(msal.SerializableTokenCache())
        flow = app.initiate_auth_code_flow(
            self.settings.microsoft_scope_list, redirect_uri=redirect_uri, prompt="select_account",
            response_mode="form_post",  # code arrives in a POST body, not in URLs and logs
        )
        if "auth_uri" not in flow:
            raise ShoppingError(flow.get("error_description") or flow.get("error") or "sign-in failed")
        self._row().auth_flow = self._encrypt(json.dumps(flow))
        self.session.commit()
        return flow["auth_uri"]

    def finish(self, params: dict[str, str]) -> str:
        """Complete a sign-in with the callback's query parameters. Returns the username."""
        row = self.account()
        flow = self._decrypt(row.auth_flow) if row else None
        if not flow:
            raise ShoppingError("No sign-in in progress. Start again.")
        if "error" in params:
            row.auth_flow = None
            self.session.commit()
            raise ShoppingError(params.get("error_description") or params["error"])
        cache = msal.SerializableTokenCache()
        app = self._app_factory(cache)
        try:
            result = app.acquire_token_by_auth_code_flow(json.loads(flow), params)
        except ValueError as e:  # state mismatch etc.
            raise ShoppingError(f"Sign-in response didn't match: {e}") from e
        if "error" in result:
            raise ShoppingError(result.get("error_description") or result["error"])
        claims = result.get("id_token_claims") or {}
        username = claims.get("preferred_username") or claims.get("email") or claims.get("name") or "?"
        if row.username != username:
            row.list_id = row.list_name = None
        row.username = username
        row.token_cache = self._encrypt(cache.serialize())
        row.auth_flow = None
        self.session.commit()
        return username

    def token(self) -> str:
        """A valid Graph access token, refreshed if needed. Raises NotConnected."""
        row = self.account()
        cache = self._load_cache(row)
        if not row or not row.username:
            raise NotConnected("not connected")
        app = self._app_factory(cache)
        accounts = app.get_accounts()
        if not accounts:
            raise NotConnected("not connected")
        result = app.acquire_token_silent(self.settings.microsoft_scope_list, account=accounts[0])
        if not result or "access_token" not in result:
            raise NotConnected((result or {}).get("error_description") or "sign-in expired")
        if cache.has_state_changed:
            row.token_cache = self._encrypt(cache.serialize())
            self.session.commit()
        return result["access_token"]

    def disconnect(self) -> None:
        row = self.account()
        if row:
            self.session.delete(row)
            self.session.commit()

    def set_default_list(self, list_id: str, name: str) -> None:
        row = self._row()
        row.list_id, row.list_name = list_id, name
        self.session.commit()


class GraphToDo:
    """Microsoft To Do lists and tasks for the signed-in user."""

    def __init__(self, access_token: str, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(
            base_url=GRAPH, timeout=15, transport=transport,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def _request(self, method: str, url: str, **kw) -> dict:
        try:
            r = self.client.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise ShoppingError(f"Microsoft Graph unreachable: {e}") from e
        if r.status_code == 401:
            raise NotConnected("access denied; connect again")
        if r.status_code >= 400:
            try:
                msg = r.json()["error"]["message"]
            except Exception:
                msg = r.text[:200]
            raise ShoppingError(f"Microsoft Graph {r.status_code}: {msg}")
        return r.json() if r.content else {}

    def _all(self, url: str, params: dict | None = None) -> list[dict]:
        out, data = [], self._request("GET", url, params=params)
        out += data.get("value", [])
        while data.get("@odata.nextLink"):  # absolute URL with the query baked in
            data = self._request("GET", data["@odata.nextLink"])
            out += data.get("value", [])
        return out

    def lists(self) -> list[ShoppingListInfo]:
        return [
            ShoppingListInfo(id=x["id"], name=x.get("displayName", ""),
                             is_default=x.get("wellknownListName") == "defaultList")
            for x in self._all("/me/todo/lists")
        ]

    def open_titles(self, list_id: str) -> list[str]:
        url = f"/me/todo/lists/{quote(list_id, safe='')}/tasks"
        tasks = self._all(url, {"$filter": "status ne 'completed'", "$top": "100"})
        return [t.get("title", "") for t in tasks if t.get("status") != "completed"]

    def add_items(self, list_id: str, titles: list[str], note: str = "") -> None:
        url = f"/me/todo/lists/{quote(list_id, safe='')}/tasks"
        for title in titles:
            body = {"title": title}
            if note:
                body["body"] = {"content": note, "contentType": "text"}
            self._request("POST", url, json=body)
