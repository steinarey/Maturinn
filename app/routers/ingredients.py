"""Canonical ingredient admin: names per language, aliases, groups, merging."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import Ingredient, IngredientName, RecipeIngredient
from app.services import ingredients as ing_svc
from app.services import search as search_svc
from app.web import request_lang, templates

router = APIRouter(prefix="/ingredients")


def _all(session: Session) -> list[Ingredient]:
    return list(session.execute(select(Ingredient)).scalars())


def _usage(session: Session) -> dict[int, int]:
    return dict(session.execute(
        select(RecipeIngredient.ingredient_id, func.count(func.distinct(RecipeIngredient.recipe_id)))
        .group_by(RecipeIngredient.ingredient_id)
    ).all())


@router.get("", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    lang = request_lang(request)
    ings = sorted(_all(session), key=lambda i: i.name_in(lang).casefold())
    return templates.TemplateResponse(request, "ingredients.html", {
        "ingredients": ings, "usage": _usage(session),
        "langs": get_settings().languages,
    })


def _detail(request: Request, session: Session, ing: Ingredient, error: str | None = None, status=200):
    lang = request_lang(request)
    others = sorted((i for i in _all(session) if i.id != ing.id), key=lambda i: i.name_in(lang).casefold())
    names = {}
    for code in get_settings().languages:
        own = [n for n in ing.names if n.lang == code]
        primary = next((n.name for n in own if n.is_primary), own[0].name if own else "")
        names[code] = {"primary": primary, "aliases": ", ".join(n.name for n in own if n.name != primary)}
    return templates.TemplateResponse(request, "ingredient_edit.html", {
        "ing": ing, "names": names, "others": others, "error": error,
        "usage": _usage(session).get(ing.id, 0),
    }, status_code=status)


@router.get("/{ing_id}", response_class=HTMLResponse)
def detail(ing_id: int, request: Request, session: Session = Depends(get_session)):
    ing = session.get(Ingredient, ing_id)
    if not ing:
        raise HTTPException(404)
    return _detail(request, session, ing)


@router.post("/{ing_id}")
async def save(ing_id: int, request: Request, session: Session = Depends(get_session)):
    ing = session.get(Ingredient, ing_id)
    if not ing:
        raise HTTPException(404)
    form = await request.form()
    try:
        for code in get_settings().languages:
            primary = form.get(f"name_{code}", "").strip()
            aliases = [a for a in form.get(f"aliases_{code}", "").split(",") if a.strip()]
            if not primary and aliases:
                primary, aliases = aliases[0], aliases[1:]
            ing_svc.set_names(session, ing, code, primary, aliases)
    except ing_svc.NameConflict as e:
        session.rollback()
        return _detail(request, session, session.get(Ingredient, ing_id), error=str(e), status=409)
    if not ing.names:
        session.rollback()
        return _detail(request, session, session.get(Ingredient, ing_id), error="", status=422)
    parent = form.get("parent_id", "")
    new_parent = int(parent) if parent.isdigit() else None
    if new_parent and new_parent in ing_svc.with_descendants(session, {ing.id}):
        new_parent = None  # would create a cycle
    ing.parent_id = new_parent
    ing.food_id = form.get("food_id", "").strip() or None
    search_svc.reindex_ingredient(session, ing.id)
    session.commit()
    return RedirectResponse(f"/ingredients/{ing.id}", status_code=303)


@router.post("/{ing_id}/merge")
async def merge(ing_id: int, request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    target_id = form.get("target_id", "")
    source = session.get(Ingredient, ing_id)
    target = session.get(Ingredient, int(target_id)) if target_id.isdigit() else None
    if not source or not target:
        raise HTTPException(404)
    ing_svc.merge(session, source, target)
    search_svc.reindex_ingredient(session, target.id)
    session.commit()
    return RedirectResponse(f"/ingredients/{target.id}", status_code=303)


@router.post("/{ing_id}/delete")
def delete(ing_id: int, session: Session = Depends(get_session)):
    ing = session.get(Ingredient, ing_id)
    if not ing:
        raise HTTPException(404)
    if _usage(session).get(ing.id):
        raise HTTPException(409, "in use")
    session.delete(ing)
    session.commit()
    return RedirectResponse("/ingredients", status_code=303)
