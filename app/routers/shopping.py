"""Settings page (Microsoft To Do connection) and "add to shopping list" from a recipe."""
from collections.abc import Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.i18n import translate
from app.services import recipes as recipe_svc
from app.services.shopping.base import NotConnected, ShoppingError, ShoppingList, ShoppingListInfo
from app.services.shopping.items import shopping_items, title_name
from app.services.shopping.microsoft import GraphToDo, MicrosoftAuth
from app.web import request_lang, templates

router = APIRouter()


def get_ms_auth(session: Session = Depends(get_session)) -> MicrosoftAuth:
    return MicrosoftAuth(get_settings(), session)


def get_list_factory(auth: MicrosoftAuth = Depends(get_ms_auth)) -> Callable[[], ShoppingList]:
    """Opening the list needs a token (and maybe a refresh), so routes call this
    only when they need the list, and handle NotConnected themselves."""
    return lambda: GraphToDo(auth.token())


def redirect_uri(request: Request) -> str:
    return get_settings().microsoft_redirect_uri or str(request.url_for("ms_callback"))


def _require_configured() -> None:
    if not get_settings().shopping_configured:
        raise HTTPException(404)


# --- Settings -----------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, auth: MicrosoftAuth = Depends(get_ms_auth),
                  open_list: Callable[[], ShoppingList] = Depends(get_list_factory),
                  error: str = "", ok: str = ""):
    ctx = {"configured": get_settings().shopping_configured, "account": None, "lists": [],
           "error": error, "ok": ok, "redirect_uri": redirect_uri(request)}
    if ctx["configured"] and auth.connected:
        ctx["account"] = auth.account()
        try:
            ctx["lists"] = open_list().lists()
        except NotConnected:
            ctx["error"] = ctx["error"] or "expired"
        except ShoppingError as e:
            ctx["error"] = ctx["error"] or str(e)
    return templates.TemplateResponse(request, "settings.html", ctx)


@router.post("/settings/microsoft/connect")
def ms_connect(request: Request, auth: MicrosoftAuth = Depends(get_ms_auth)):
    _require_configured()
    try:
        url = auth.begin(redirect_uri(request))
    except ShoppingError as e:
        return RedirectResponse(f"/settings?error={_q(str(e))}", status_code=303)
    return RedirectResponse(url, status_code=303)


@router.api_route("/settings/microsoft/callback", methods=["GET", "POST"], name="ms_callback")
async def ms_callback(request: Request, auth: MicrosoftAuth = Depends(get_ms_auth)):
    """Microsoft posts the result here (form_post); GET is accepted for errors shown in the URL."""
    _require_configured()
    params = dict(request.query_params)
    if request.method == "POST":
        params.update({k: v for k, v in (await request.form()).items() if isinstance(v, str)})
    try:
        auth.finish(params)
    except ShoppingError as e:
        return RedirectResponse(f"/settings?error={_q(str(e))}", status_code=303)
    return RedirectResponse("/settings?ok=connected", status_code=303)


@router.post("/settings/microsoft/disconnect")
def ms_disconnect(auth: MicrosoftAuth = Depends(get_ms_auth)):
    auth.disconnect()
    return RedirectResponse("/settings?ok=disconnected", status_code=303)


@router.post("/settings/microsoft/list")
def ms_default_list(list_id: str = Form(...), auth: MicrosoftAuth = Depends(get_ms_auth),
                    open_list: Callable[[], ShoppingList] = Depends(get_list_factory)):
    _require_configured()
    try:
        chosen = _find(open_list().lists(), list_id)
    except ShoppingError as e:
        return RedirectResponse(f"/settings?error={_q(str(e))}", status_code=303)
    if not chosen:
        raise HTTPException(400)
    auth.set_default_list(chosen.id, chosen.name)
    return RedirectResponse("/settings?ok=saved", status_code=303)


def _q(text: str) -> str:
    return quote(text[:300])


def _find(lists: list[ShoppingListInfo], list_id: str | None) -> ShoppingListInfo | None:
    return next((x for x in lists if x.id == list_id), None)


# --- Recipe -> shopping list --------------------------------------------------

def _recipe(session: Session, recipe_id: int):
    recipe = recipe_svc.load(session, recipe_id)
    if not recipe:
        raise HTTPException(404)
    return recipe


def _servings(value: str | None) -> int | None:
    try:
        n = int(value or "")
    except ValueError:
        return None
    return n if 1 <= n <= 1000 else None


def _dialog(request: Request, ctx: dict):
    return templates.TemplateResponse(request, "partials/shopping.html", ctx)


@router.get("/recipes/{recipe_id}/shopping", response_class=HTMLResponse)
def shopping_dialog(recipe_id: int, request: Request, servings: str | None = None, list_id: str | None = None,
                    session: Session = Depends(get_session), auth: MicrosoftAuth = Depends(get_ms_auth),
                    open_list: Callable[[], ShoppingList] = Depends(get_list_factory)):
    _require_configured()
    recipe = _recipe(session, recipe_id)
    n = _servings(servings)
    ctx = {"r": recipe, "servings": n or "", "error": None}
    try:
        sl = open_list()
        lists = sl.lists()
        account = auth.account()
        chosen = (_find(lists, list_id) or _find(lists, account.list_id if account else None)
                  or next((x for x in lists if x.is_default), None) or (lists[0] if lists else None))
        if chosen is None:
            raise ShoppingError("No To Do lists found.")
        on_list = {title_name(t) for t in sl.open_titles(chosen.id)}
    except NotConnected:
        return _dialog(request, {**ctx, "error": "not_connected"})
    except ShoppingError as e:
        return _dialog(request, {**ctx, "error": str(e)})
    rows = [(ing_id, item, bool(item.names & on_list))
            for ing_id, item in shopping_items(recipe, request_lang(request), n)]
    return _dialog(request, {**ctx, "lists": lists, "chosen": chosen, "rows": rows})


@router.post("/recipes/{recipe_id}/shopping", response_class=HTMLResponse)
def shopping_add(recipe_id: int, request: Request, list_id: str = Form(...), servings: str = Form(""),
                 item: list[int] = Form(default=[]),
                 session: Session = Depends(get_session), auth: MicrosoftAuth = Depends(get_ms_auth),
                 open_list: Callable[[], ShoppingList] = Depends(get_list_factory)):
    _require_configured()
    recipe = _recipe(session, recipe_id)
    lang = request_lang(request)
    ctx = {"r": recipe, "done": True, "error": None, "added": []}
    wanted = set(item)
    titles = [it.title for ing_id, it in shopping_items(recipe, lang, _servings(servings)) if ing_id in wanted]
    if not titles:
        return _dialog(request, {**ctx, "error": "nothing"})
    try:
        sl = open_list()
        chosen = _find(sl.lists(), list_id)
        if chosen is None:
            raise ShoppingError("That list no longer exists.")
        sl.add_items(chosen.id, titles, note=translate(lang, "shop.note_from", title=recipe.title))
    except NotConnected:
        return _dialog(request, {**ctx, "error": "not_connected"})
    except ShoppingError as e:
        return _dialog(request, {**ctx, "error": str(e)})
    account = auth.account()
    if not account or account.list_id != chosen.id:
        auth.set_default_list(chosen.id, chosen.name)  # remember the last list used
    return _dialog(request, {**ctx, "added": titles, "chosen": chosen})
