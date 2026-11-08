"""Settings page (Home Assistant status) and "add to shopping list" from a recipe."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.i18n import translate
from app.services import recipes as recipe_svc
from app.services.shopping.base import ShoppingError, ShoppingList, ShoppingListInfo
from app.services.shopping.homeassistant import HomeAssistantTodo
from app.services.shopping.items import shopping_items, title_name
from app.web import request_lang, templates

router = APIRouter()
LIST_COOKIE = "shop_list"  # last list used, per browser


def get_shopping_list() -> ShoppingList:
    s = get_settings()
    if not s.shopping_configured:
        raise HTTPException(404)
    return HomeAssistantTodo(s.home_assistant_url, s.home_assistant_token)


def _find(lists: list[ShoppingListInfo], list_id: str | None) -> ShoppingListInfo | None:
    return next((x for x in lists if x.id == list_id), None)


def _default(lists: list[ShoppingListInfo], request: Request) -> ShoppingListInfo | None:
    return (_find(lists, request.cookies.get(LIST_COOKIE)) or _find(lists, get_settings().home_assistant_todo)
            or (lists[0] if lists else None))


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    s = get_settings()
    ctx = {"configured": s.shopping_configured, "url": s.home_assistant_url, "lists": [], "error": None,
           "default": None}
    if s.shopping_configured:
        try:
            ha = get_shopping_list()
            ha.check()
            ctx["lists"] = ha.lists()
            ctx["default"] = _default(ctx["lists"], request)
        except ShoppingError as e:
            ctx["error"] = str(e)
    return templates.TemplateResponse(request, "settings.html", ctx)


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
                    session: Session = Depends(get_session), sl: ShoppingList = Depends(get_shopping_list)):
    recipe = _recipe(session, recipe_id)
    n = _servings(servings)
    ctx = {"r": recipe, "servings": n or "", "error": None}
    try:
        lists = sl.lists()
        chosen = _find(lists, list_id) or _default(lists, request)
        if chosen is None:
            return _dialog(request, {**ctx, "error": "no_lists"})
        on_list = {title_name(t) for t in sl.open_titles(chosen.id)}
    except ShoppingError as e:
        return _dialog(request, {**ctx, "error": str(e)})
    rows = [(ing_id, item, bool(item.names & on_list))
            for ing_id, item in shopping_items(recipe, request_lang(request), n)]
    return _dialog(request, {**ctx, "lists": lists, "chosen": chosen, "rows": rows})


@router.post("/recipes/{recipe_id}/shopping", response_class=HTMLResponse)
def shopping_add(recipe_id: int, request: Request, list_id: str = Form(...), servings: str = Form(""),
                 item: list[int] = Form(default=[]),
                 session: Session = Depends(get_session), sl: ShoppingList = Depends(get_shopping_list)):
    recipe = _recipe(session, recipe_id)
    lang = request_lang(request)
    ctx = {"r": recipe, "done": True, "error": None, "added": []}
    wanted = set(item)
    titles = [it.title for ing_id, it in shopping_items(recipe, lang, _servings(servings)) if ing_id in wanted]
    if not titles:
        return _dialog(request, {**ctx, "error": "nothing"})
    try:
        chosen = _find(sl.lists(), list_id)
        if chosen is None:
            raise ShoppingError(f"List {list_id} not found in Home Assistant.")
        sl.add_items(chosen.id, titles, note=translate(lang, "shop.note_from", title=recipe.title))
    except ShoppingError as e:
        return _dialog(request, {**ctx, "error": str(e)})
    resp = _dialog(request, {**ctx, "added": titles, "chosen": chosen})
    resp.set_cookie(LIST_COOKIE, chosen.id, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp
