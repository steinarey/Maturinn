"""Server-rendered pages: recipe list/search, read view, write view."""
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app import units
from app.config import get_settings
from app.db import get_session
from app.i18n import format_qty, parse_qty
from app.models import Recipe
from app.services import ingredients as ing_svc
from app.services import links as link_svc
from app.services import photos as photo_svc
from app.services import recipes as recipe_svc
from app.services import search as search_svc
from app.web import THEMES, request_lang, templates

router = APIRouter()


def _split(value: str) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


# --- Language and theme -----------------------------------------------------

def _back(request: Request) -> str:
    ref = request.headers.get("referer") or "/"
    parsed = urlparse(ref)
    # Only redirect within this site.
    return (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")


@router.get("/set-lang/{lang}")
def set_lang(lang: str, request: Request):
    if lang not in get_settings().languages:
        raise HTTPException(404)
    resp = RedirectResponse(_back(request), status_code=303)
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


@router.get("/set-theme/{theme}")
def set_theme(theme: str, request: Request):
    if theme not in THEMES:
        raise HTTPException(404)
    resp = RedirectResponse(_back(request), status_code=303)
    resp.set_cookie("theme", theme, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


# --- List and search ----------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", has: str = "", without: str = "",
          session: Session = Depends(get_session)):
    result = search_svc.search(session, q, _split(has), _split(without))
    ctx = {"result": result, "q": q, "has": has, "without": without,
           "cover": recipe_svc.cover_photo, "thumb": photo_svc.thumb_path,
           "tag_name": recipe_svc.tag_name}
    name = "partials/results.html" if request.headers.get("hx-request") else "index.html"
    return templates.TemplateResponse(request, name, ctx)


# --- Read view ----------------------------------------------------------------

# Must be declared before /recipes/{recipe_id}: FastAPI does not fall through
# to the next route when "new" fails int parsing.
@router.get("/recipes/new", response_class=HTMLResponse)
def new(request: Request):
    return _edit(request, blank_form(request_lang(request)))


@router.get("/recipes/{recipe_id}", response_class=HTMLResponse)
def read(recipe_id: int, request: Request, session: Session = Depends(get_session)):
    recipe = recipe_svc.load(session, recipe_id)
    if not recipe:
        raise HTTPException(404)
    ids = link_svc.recipe_ids(recipe.description, *(s.text for s in recipe.steps),
                              *(i.note for i in recipe.ingredients))
    existing = link_svc.existing_ids(session, ids)
    return templates.TemplateResponse(request, "recipe_read.html", {
        "r": recipe, "tag_name": recipe_svc.tag_name, "thumb": photo_svc.thumb_path,
        "rich": lambda text: link_svc.render(text, existing),
        "linked_from": link_svc.linked_from(session, recipe.id),
    })


@router.get("/recipes/{recipe_id}/amounts")
def amounts(recipe_id: int, request: Request, servings: int | None = None, metric: bool = False,
            session: Session = Depends(get_session)):
    """Ingredient amounts as text, scaled to `servings` (cups as dl/ml if `metric`). Used by the read view's scaler."""
    recipe = recipe_svc.load(session, recipe_id)
    if not recipe:
        raise HTTPException(404)
    factor = servings / recipe.servings if servings and servings > 0 and recipe.servings else 1
    lang = request_lang(request)
    return {str(ri.id): units.amount(ri.quantity, ri.unit, lang, factor=factor, metric=metric)
            for ri in recipe.ingredients}


# --- Write view ---------------------------------------------------------------

def _key() -> str:
    return uuid.uuid4().hex[:10]


def form_from_input(data: recipe_svc.RecipeIn, lang: str) -> dict:
    """View model for the edit template. Quantities shown in the UI locale."""
    return {
        "title": data.title, "description": data.description,
        "servings": data.servings or "", "original_lang": data.original_lang,
        "source_url": data.source_url or "", "tags": ", ".join(data.tags),
        "ingredients": ingredient_rows(data.ingredients, lang),
        "items": [{"id": i.id or "", "name": i.name} for i in data.items],
        "steps": [{"key": _key(), "id": s.id or "", "text": s.text,
                   "photos": [p.model_dump() for p in s.photos]} for s in data.steps],
    }


def ingredient_rows(ingredients: list[recipe_svc.IngredientIn], lang: str) -> list[dict]:
    """Ingredient rows for the edit view, with a heading row wherever the section changes."""
    rows, current = [], ""
    for i in ingredients:
        if i.section != current:
            current = i.section
            if current:
                rows.append({"kind": "sec", "name": current})
        rows.append({"kind": "ing", "id": i.id or "", "qty": format_qty(i.quantity, lang), "unit": i.unit,
                     "name": i.name, "note": i.note})
    return rows


def blank_form(lang: str) -> dict:
    return {
        "title": "", "description": "", "servings": "", "original_lang": lang, "source_url": "",
        "tags": "", "ingredients": [{"kind": "ing", "id": "", "qty": "", "unit": "", "name": "", "note": ""}],
        "items": [], "steps": [{"key": _key(), "id": "", "text": "", "photos": []}],
    }


def parse_form(form: FormData) -> tuple[dict, recipe_svc.RecipeIn | None, dict[str, str]]:
    """Returns (view model for re-render, validated input or None, errors)."""
    errors: dict[str, str] = {}
    g = form.getlist
    ing_fields = [{"kind": "ing", "id": i, "qty": q, "unit": u, "name": n, "note": no}
                  for i, q, u, n, no in zip(g("ing_id"), g("ing_qty"), g("ing_unit"), g("ing_name"), g("ing_note"))]
    # Ingredient and section-heading rows share one list; row_kind gives their DOM order.
    kinds = g("row_kind") or ["ing"] * len(ing_fields)
    ing_iter, sec_iter = iter(ing_fields), iter(g("sec_name"))
    ings = []
    for kind in kinds:
        if kind == "sec":
            ings.append({"kind": "sec", "name": next(sec_iter, "")})
        else:
            row = next(ing_iter, None)
            if row is not None:
                ings.append(row)
    items = [{"id": i, "name": n} for i, n in zip(g("item_id"), g("item_name"))]
    steps = []
    for key, sid, txt in zip(g("step_key"), g("step_id"), g("step_text")):
        photos = [{"path": p, "caption": c}
                  for p, c in zip(g(f"photo_path_{key}"), g(f"photo_caption_{key}"))]
        steps.append({"key": key, "id": sid, "text": txt, "photos": photos})
    vm = {
        "title": form.get("title", ""), "description": form.get("description", ""),
        "servings": form.get("servings", ""), "original_lang": form.get("original_lang", "is"),
        "source_url": form.get("source_url", ""), "tags": form.get("tags", ""),
        "ingredients": ings, "items": items, "steps": steps,
    }

    parsed_ings = []
    section = ""
    for n, row in enumerate(ings):
        if row["kind"] == "sec":
            section = row["name"].strip()
            continue
        if not row["name"].strip():
            if row["qty"].strip() or row["unit"].strip():
                errors[f"ing_{n}"] = "error.ingredient_name"
            continue
        try:
            qty = parse_qty(row["qty"])
        except ValueError:
            errors[f"ing_{n}"] = "error.quantity"
            continue
        parsed_ings.append(recipe_svc.IngredientIn(
            id=int(row["id"]) if row["id"].isdigit() else None, quantity=qty,
            unit=row["unit"], name=row["name"], note=row["note"], section=section))

    servings = vm["servings"].strip()
    if servings and not servings.isdigit():
        errors["servings"] = "error.servings"
    data = None
    try:
        data = recipe_svc.RecipeIn(
            title=vm["title"], description=vm["description"],
            servings=int(servings) if servings.isdigit() else None,
            original_lang=vm["original_lang"], source_url=vm["source_url"],
            tags=_split(vm["tags"]), ingredients=parsed_ings,
            items=[recipe_svc.ItemIn(id=int(i["id"]) if i["id"].isdigit() else None, name=i["name"])
                   for i in items],
            steps=[recipe_svc.StepIn(id=int(s["id"]) if s["id"].isdigit() else None, text=s["text"],
                                     photos=[recipe_svc.PhotoIn(**p) for p in s["photos"]])
                   for s in steps],
        )
    except ValidationError as e:
        for err in e.errors():
            field = str(err["loc"][0]) if err["loc"] else "form"
            errors.setdefault(field, f"error.{field}")
    return vm, (None if errors else data), errors


def _edit(request: Request, form: dict, recipe: Recipe | None = None,
          errors: dict | None = None, status: int = 200, draft=None):
    return templates.TemplateResponse(request, "recipe_edit.html", {
        "form": form, "recipe": recipe, "errors": errors or {}, "thumb": photo_svc.thumb_path,
        "draft": draft,
    }, status_code=status)


@router.post("/recipes")
async def create(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    vm, data, errors = parse_form(form)
    draft = None
    if form.get("draft_id", "").isdigit():
        from app.models import ImportDraft
        draft = session.get(ImportDraft, int(form["draft_id"]))
    if errors:
        return _edit(request, vm, errors=errors, status=422, draft=draft)
    recipe = recipe_svc.save(session, data)
    if draft:
        from app.routers.imports import mark_saved
        mark_saved(session, str(draft.id), recipe.id)
    session.commit()
    return RedirectResponse(f"/recipes/{recipe.id}", status_code=303)


@router.get("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
def edit(recipe_id: int, request: Request, session: Session = Depends(get_session)):
    recipe = recipe_svc.load(session, recipe_id)
    if not recipe:
        raise HTTPException(404)
    return _edit(request, form_from_input(recipe_svc.to_input(recipe), request_lang(request)), recipe)


@router.post("/recipes/{recipe_id}")
async def update(recipe_id: int, request: Request, session: Session = Depends(get_session)):
    recipe = recipe_svc.load(session, recipe_id)
    if not recipe:
        raise HTTPException(404)
    vm, data, errors = parse_form(await request.form())
    if errors:
        return _edit(request, vm, recipe, errors, status=422)
    recipe_svc.save(session, data, recipe)
    session.commit()
    return RedirectResponse(f"/recipes/{recipe.id}", status_code=303)


@router.post("/recipes/{recipe_id}/delete")
def delete(recipe_id: int, session: Session = Depends(get_session)):
    recipe = session.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(404)
    session.delete(recipe)
    session.commit()
    return RedirectResponse("/", status_code=303)


# --- Edit-view fragments (HTMX) --------------------------------------------------

@router.get("/fragments/{kind}-row", response_class=HTMLResponse)
def blank_row(kind: str, request: Request):
    rows = {
        "ingredient": ("partials/ing_row.html", {"row": {"kind": "ing", "id": "", "qty": "", "unit": "", "name": "", "note": ""}}),
        "section": ("partials/sec_row.html", {"row": {"kind": "sec", "name": ""}}),
        "item": ("partials/item_row.html", {"row": {"id": "", "name": ""}}),
        "step": ("partials/step_row.html", {"row": {"key": _key(), "id": "", "text": "", "photos": []}}),
    }
    if kind not in rows:
        raise HTTPException(404)
    name, ctx = rows[kind]
    return templates.TemplateResponse(request, name, {**ctx, "thumb": photo_svc.thumb_path, "errors": {}})


@router.post("/fragments/photo", response_class=HTMLResponse)
def upload_photo(request: Request, key: str = Form(...), files: list[UploadFile] = File(...)):
    out = []
    for f in files:
        try:
            out.append(photo_svc.save_upload(f.file))
        except photo_svc.BadImage:
            continue
    if not out:
        return Response(status_code=422)
    return templates.TemplateResponse(request, "partials/photos.html", {
        "key": key, "photos": [{"path": p, "caption": ""} for p in out], "thumb": photo_svc.thumb_path,
    })


@router.get("/fragments/ingredient-check", response_class=HTMLResponse)
def ingredient_check(request: Request, ing_name: str = "", session: Session = Depends(get_session)):
    """Shows whether a typed name maps to an existing canonical ingredient."""
    lang = request_lang(request)
    name = ing_name
    match = None
    if name.strip():
        match = ing_svc.find(session, name) or ing_svc.find_inflected(session, name)
    suggestions = [] if match or not name.strip() else ing_svc.suggest(session, name, limit=3)
    return templates.TemplateResponse(request, "partials/ing_check.html", {
        "name": name, "match": match, "match_name": match.name_in(lang) if match else "",
        "suggestions": suggestions,
    })


@router.get("/fragments/ingredient-options", response_class=HTMLResponse)
def ingredient_options(request: Request, ing_name: str = "", session: Session = Depends(get_session)):
    """<option>s for the shared ingredient <datalist> while typing."""
    sugg = ing_svc.suggest(session, ing_name, limit=8) if len(ing_name.strip()) >= 2 else []
    return templates.TemplateResponse(request, "partials/ing_options.html", {"suggestions": sugg})


@router.get("/fragments/recipe-links", response_class=HTMLResponse)
def recipe_links(request: Request, q: str = "", exclude: int | None = None,
                 session: Session = Depends(get_session)):
    """Choices for the "link a recipe" picker in the write view."""
    found = [r for r in search_svc.search(session, q, limit=12).recipes if r.id != exclude]
    return templates.TemplateResponse(request, "partials/recipe_links.html", {
        "found": found, "link": link_svc.recipe_link})
