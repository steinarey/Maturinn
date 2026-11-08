"""Import a recipe from a URL or pasted text. Runs in the background worker;
these pages create the draft, show progress, and open it for review."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import ImportDraft
from app.routers.pages import form_from_input
from app.services import importer
from app.services import photos as photo_svc
from app.services import recipes as recipe_svc
from app.web import request_lang, templates

router = APIRouter(prefix="/import")
RUNNING = ("pending", "fetching", "extracting")


def _get(session: Session, draft_id: int) -> ImportDraft:
    row = session.get(ImportDraft, draft_id)
    if not row:
        raise HTTPException(404)
    return row


def _form(request: Request, session: Session, errors: dict | None = None, status: int = 200, **values):
    recent = session.execute(select(ImportDraft).order_by(ImportDraft.id.desc()).limit(10)).scalars().all()
    ctx = {"recent": recent, "errors": errors or {}, "source": "url", "url": "", "text": "", "instructions": "",
           "max_images": importer.MAX_IMAGES}
    ctx.update(values)
    return templates.TemplateResponse(request, "import.html", ctx, status_code=status)


@router.get("", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    return _form(request, session)


@router.post("")
async def create(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    source = form.get("source") or ("url" if form.get("url") else "text")
    url = (form.get("url") or "").strip()
    text = (form.get("text") or "").strip()
    instructions = (form.get("instructions") or "").strip()[:2000]
    uploads = [f for f in form.getlist("images") if getattr(f, "filename", "")]
    values = {"source": source, "url": url, "text": text, "instructions": instructions}

    if not get_settings().llm_configured:
        return _form(request, session, {"form": "import.no_llm"}, 422, **values)
    if source == "url":
        if not url:
            return _form(request, session, {"form": "import.need_input"}, 422, **values)
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        row = ImportDraft(kind="url", url=url)
    elif source == "text":
        if not text:
            return _form(request, session, {"form": "import.need_input"}, 422, **values)
        row = ImportDraft(kind="text", source_text=text)
    elif source == "image":
        if not uploads:
            return _form(request, session, {"form": "import.need_images"}, 422, **values)
        if len(uploads) > importer.MAX_IMAGES:
            return _form(request, session, {"form": "import.too_many_images"}, 422, **values)
        paths = []
        for f in uploads:
            try:
                paths.append(photo_svc.save_scaled(f.file, "imports", 1600))
            except photo_svc.BadImage:
                return _form(request, session, {"form": "import.bad_image"}, 422, **values)
        row = ImportDraft(kind="image", images=paths)
    else:
        raise HTTPException(400)
    row.instructions = instructions
    row.status, row.events = "pending", []
    session.add(row)
    session.commit()
    return RedirectResponse(f"/import/{row.id}", status_code=303)


def _progress_ctx(row: ImportDraft) -> dict:
    return {"row": row, "running": row.status in RUNNING}


@router.get("/{draft_id}", response_class=HTMLResponse)
def show(draft_id: int, request: Request, session: Session = Depends(get_session)):
    row = _get(session, draft_id)
    if row.status == "ready":
        return RedirectResponse(f"/import/{row.id}/review", status_code=303)
    return templates.TemplateResponse(request, "import_progress.html", _progress_ctx(row))


@router.get("/{draft_id}/progress", response_class=HTMLResponse)
def progress(draft_id: int, request: Request, session: Session = Depends(get_session)):
    row = _get(session, draft_id)
    if row.status == "ready":
        return Response(headers={"HX-Redirect": f"/import/{row.id}/review"})
    return templates.TemplateResponse(request, "partials/import_progress.html", _progress_ctx(row))


@router.post("/{draft_id}/retry")
def retry(draft_id: int, session: Session = Depends(get_session)):
    row = _get(session, draft_id)
    if row.status != "failed":
        raise HTTPException(409)
    row.status, row.error, row.draft, row.events = "pending", None, None, []
    if row.kind == "url":
        row.source_text = None
    session.commit()
    return RedirectResponse(f"/import/{row.id}", status_code=303)


@router.get("/{draft_id}/review", response_class=HTMLResponse)
def review(draft_id: int, request: Request, session: Session = Depends(get_session)):
    row = _get(session, draft_id)
    if row.status == "saved" and row.recipe_id:
        return RedirectResponse(f"/recipes/{row.recipe_id}", status_code=303)
    if row.status != "ready":
        return RedirectResponse(f"/import/{row.id}", status_code=303)
    try:
        data = recipe_svc.RecipeIn(**row.draft)
    except ValidationError:
        data = recipe_svc.RecipeIn(**{**row.draft, "title": row.draft.get("title") or "?"})
    return templates.TemplateResponse(request, "recipe_edit.html", {
        "form": form_from_input(data, request_lang(request)), "recipe": None, "errors": {},
        "thumb": photo_svc.thumb_path, "draft": row,
    })


@router.post("/{draft_id}/delete")
def delete(draft_id: int, session: Session = Depends(get_session)):
    row = _get(session, draft_id)
    if row.status in RUNNING and row.status != "pending":
        raise HTTPException(409)
    images = list(row.images or [])
    session.delete(row)
    session.commit()
    for rel in images:  # uploaded source photos belong to the draft only
        (get_settings().photos_dir / rel).unlink(missing_ok=True)
    return RedirectResponse("/import", status_code=303)


def mark_saved(session: Session, draft_id: str | None, recipe_id: int) -> None:
    """Called when a reviewed draft is saved as a recipe."""
    if draft_id and draft_id.isdigit():
        row = session.get(ImportDraft, int(draft_id))
        if row and row.status == "ready":
            row.status = "saved"
            row.recipe_id = recipe_id
            importer.add_event(row, {"t": "saved"})
