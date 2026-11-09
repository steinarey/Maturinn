"""Links inside recipe text: [label](recipe:12) to another recipe, or [label](https://...).

Stored as plain text in steps, descriptions and ingredient notes, so it survives
editing, export and (later) translation. Rendered to HTML only in the read view.
"""
import re

from markupsafe import Markup, escape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Recipe, RecipeIngredient, Step

LINK_RE = re.compile(r"\[([^\[\]\n]{1,200})\]\((?:recipe:(\d+)|(https?://[^\s()<>]+))\)")


def recipe_ids(*texts: str | None) -> set[int]:
    return {int(m.group(2)) for t in texts if t for m in LINK_RE.finditer(t) if m.group(2)}


def recipe_link(recipe_id: int, label: str) -> str:
    label = re.sub(r"[\[\]\n]", "", label).strip() or str(recipe_id)
    return f"[{label}](recipe:{recipe_id})"


def render(text: str | None, existing: set[int] | None = None) -> Markup:
    """HTML for display. Links to deleted recipes become plain text; everything else is escaped."""
    if not text:
        return Markup("")
    out, pos = [], 0
    for m in LINK_RE.finditer(text):
        out.append(escape(text[pos:m.start()]))
        label, rid, url = m.group(1), m.group(2), m.group(3)
        if rid and (existing is None or int(rid) in existing):
            out.append(Markup('<a class="rlink" href="/recipes/{}">{}</a>').format(int(rid), label))
        elif url:
            out.append(Markup('<a href="{}" rel="noopener noreferrer" target="_blank">{}</a>').format(url, label))
        else:
            out.append(escape(label))
        pos = m.end()
    out.append(escape(text[pos:]))
    return Markup("").join(out)


def plain(text: str | None) -> str:
    """Text with link markup reduced to the labels."""
    return LINK_RE.sub(lambda m: m.group(1), text or "")


def existing_ids(session: Session, ids: set[int]) -> set[int]:
    if not ids:
        return set()
    return set(session.execute(select(Recipe.id).where(Recipe.id.in_(ids))).scalars())


def recipes(session: Session, ids: set[int]) -> list[Recipe]:
    """The recipes with these ids, by title (e.g. the ones a recipe links to)."""
    if not ids:
        return []
    return list(session.execute(select(Recipe).where(Recipe.id.in_(ids)).order_by(Recipe.title)).scalars())


def linked_from(session: Session, recipe_id: int) -> list[Recipe]:
    """Recipes whose text links to this one."""
    pattern = f"%(recipe:{recipe_id})%"
    ids = set(session.execute(select(Step.recipe_id).where(Step.text.like(pattern))).scalars())
    ids |= set(session.execute(
        select(RecipeIngredient.recipe_id).where(RecipeIngredient.note.like(pattern))).scalars())
    ids |= set(session.execute(select(Recipe.id).where(Recipe.description.like(pattern))).scalars())
    ids.discard(recipe_id)
    if not ids:
        return []
    return list(session.execute(select(Recipe).where(Recipe.id.in_(ids)).order_by(Recipe.title)).scalars())


