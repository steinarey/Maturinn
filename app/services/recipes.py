"""Recipe input schema and persistence, shared by the HTML forms and the JSON API.

`RecipeIn` is also the draft format: an import (later phase) produces a
RecipeIn that the write view renders for the user to edit before saving.
"""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Recipe, RecipeIngredient, RecipeItem, Step, StepPhoto, Tag, TagName,
)
from app.services import ingredients as ing_svc
from app.services import search

Lang = Literal["is", "en"]


class IngredientIn(BaseModel):
    id: int | None = None
    quantity: Decimal | None = None
    unit: str = ""
    name: str
    note: str = ""
    section: str = ""  # group heading, e.g. "Deig"; empty = none


class ItemIn(BaseModel):
    id: int | None = None
    name: str


class PhotoIn(BaseModel):
    path: str
    caption: str = ""


class StepIn(BaseModel):
    id: int | None = None
    text: str = ""
    photos: list[PhotoIn] = []


class RecipeIn(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    servings: int | None = Field(default=None, ge=1, le=1000)
    original_lang: Lang = "is"
    source_url: str | None = None
    tags: list[str] = []
    ingredients: list[IngredientIn] = []
    items: list[ItemIn] = []
    steps: list[StepIn] = []

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty")
        return v


class RecipeOut(RecipeIn):
    id: int
    created_at: datetime
    updated_at: datetime


def load(session: Session, recipe_id: int) -> Recipe | None:
    return session.execute(
        select(Recipe).where(Recipe.id == recipe_id).options(
            selectinload(Recipe.ingredients),
            selectinload(Recipe.items),
            selectinload(Recipe.steps).selectinload(Step.photos),
            selectinload(Recipe.tags),
        )
    ).scalar_one_or_none()


def tag_name(tag: Tag, lang: str) -> str:
    for n in tag.names:
        if n.lang == lang:
            return n.name
    return tag.names[0].name if tag.names else ""


def resolve_tag(session: Session, name: str, lang: str) -> Tag:
    norm = ing_svc.normalize(name)
    tag_id = session.execute(
        select(TagName.tag_id).where(TagName.norm == norm)
        .order_by((TagName.lang == lang).desc()).limit(1)
    ).scalar()
    if tag_id:
        return session.get(Tag, tag_id)
    tag = Tag(names=[TagName(lang=lang, name=name.strip(), norm=norm)])
    session.add(tag)
    session.flush()
    return tag


def _same_ingredient(row: RecipeIngredient, name: str) -> bool:
    norm = ing_svc.normalize(name)
    return any(n.norm == norm for n in row.ingredient.names)


def save(session: Session, data: RecipeIn, recipe: Recipe | None = None) -> Recipe:
    """Create or update a recipe. Child rows keep their ids when the input carries them,
    so cached translations and nutrition matches survive unrelated edits."""
    if recipe is None:
        recipe = Recipe()
        session.add(recipe)
    lang = data.original_lang
    recipe.title = data.title
    recipe.description = data.description.strip()
    recipe.servings = data.servings
    recipe.original_lang = lang
    recipe.source_url = (data.source_url or "").strip() or None
    recipe.updated_at = func.now()  # child-only edits must bump it too

    # Tags: dedupe by normalized name, keep input order.
    tags, seen = [], set()
    for raw in data.tags:
        if ing_svc.normalize(raw) and ing_svc.normalize(raw) not in seen:
            seen.add(ing_svc.normalize(raw))
            tags.append(resolve_tag(session, raw, lang))
    recipe.tags = tags

    # Ingredients
    existing = {r.id: r for r in recipe.ingredients}
    rows = []
    for pos, item in enumerate(i for i in data.ingredients if i.name.strip()):
        row = existing.get(item.id) if item.id else None
        if row is None or not _same_ingredient(row, item.name):
            ing, _ = ing_svc.resolve(session, item.name, lang)
            if row is None:
                row = RecipeIngredient(ingredient=ing)
            else:
                row.ingredient = ing
                row.food_id = None  # different ingredient: old nutrition match is invalid
                row.match_confidence = None
        row.quantity = item.quantity
        row.unit = item.unit.strip()
        row.note = item.note.strip()
        row.section = item.section.strip()
        row.position = pos
        rows.append(row)
    recipe.ingredients = rows

    # "You'll need" items
    existing_items = {r.id: r for r in recipe.items}
    items = []
    for pos, it in enumerate(i for i in data.items if i.name.strip()):
        row = existing_items.get(it.id) if it.id else None
        row = row or RecipeItem()
        row.name = it.name.strip()
        row.position = pos
        items.append(row)
    recipe.items = items

    # Steps with photos
    existing_steps = {s.id: s for s in recipe.steps}
    steps = []
    for pos, st in enumerate(s for s in data.steps if s.text.strip() or s.photos):
        row = existing_steps.get(st.id) if st.id else None
        row = row or Step()
        row.text = st.text.strip()
        row.position = pos
        row.photos = [StepPhoto(path=p.path, caption=p.caption.strip(), position=i)
                      for i, p in enumerate(st.photos)]
        steps.append(row)
    recipe.steps = steps

    session.flush()
    search.reindex(session, recipe.id)
    return recipe


def to_input(recipe: Recipe) -> RecipeIn:
    """The editable form of a saved recipe, in its original language."""
    lang = recipe.original_lang
    return RecipeIn(
        title=recipe.title,
        description=recipe.description,
        servings=recipe.servings,
        original_lang=lang,
        source_url=recipe.source_url,
        tags=[tag_name(t, lang) for t in recipe.tags],
        ingredients=[
            IngredientIn(id=r.id, quantity=r.quantity, unit=r.unit,
                         name=r.ingredient.name_in(lang), note=r.note, section=r.section)
            for r in recipe.ingredients
        ],
        items=[ItemIn(id=i.id, name=i.name) for i in recipe.items],
        steps=[
            StepIn(id=s.id, text=s.text, photos=[PhotoIn(path=p.path, caption=p.caption) for p in s.photos])
            for s in recipe.steps
        ],
    )


def to_output(recipe: Recipe) -> RecipeOut:
    return RecipeOut(**to_input(recipe).model_dump(), id=recipe.id,
                     created_at=recipe.created_at, updated_at=recipe.updated_at)


def cover_photo(recipe: Recipe) -> str | None:
    """Last photo of the last step that has one: usually the finished dish."""
    for step in reversed(recipe.steps):
        if step.photos:
            return step.photos[-1].path
    return None
