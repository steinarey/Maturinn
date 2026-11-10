"""Recipe search over titles, ingredients and tags, in Icelandic and English.

Each recipe has one `recipe_search` row, rebuilt on save:
  doc_simple  - tsvector, 'simple' config (no stemming; used for Icelandic)
  doc_english - tsvector, 'english' config (stems "breasts" -> "breast")
  text_all    - normalized title + ingredient names + tags, for pg_trgm

Postgres has no Icelandic stemmer, so each query word matches when ANY of:
  1. a prefix query on a shortened stem (kjúklingabringur -> kjúklingabring:*)
  2. the English stemmed query
  3. trigram word similarity against text_all (catches other endings: laukur/laukar)
Words are ANDed. Ingredient filters (has / without) work on canonical ids.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from app.models import (
    IngredientName, Recipe, RecipeIngredient, RecipeTag, RecipeTranslation, Step, TagName,
)
from app.services import ingredients as ing_svc

TRIGRAM_THRESHOLD = 0.5
SHORT_WORD_THRESHOLD = 0.75


def reindex(session: Session, recipe_id: int) -> None:
    recipe = session.get(Recipe, recipe_id)
    titles = [recipe.title] + list(session.execute(
        select(RecipeTranslation.title).where(RecipeTranslation.recipe_id == recipe_id)
    ).scalars())
    descs = [recipe.description] + list(session.execute(
        select(RecipeTranslation.description).where(RecipeTranslation.recipe_id == recipe_id)
    ).scalars())
    ing_names = list(session.execute(
        select(IngredientName.name).join(
            RecipeIngredient, RecipeIngredient.ingredient_id == IngredientName.ingredient_id
        ).where(RecipeIngredient.recipe_id == recipe_id).distinct()
    ).scalars())
    tag_names = list(session.execute(
        select(TagName.name).join(RecipeTag, RecipeTag.tag_id == TagName.tag_id)
        .where(RecipeTag.recipe_id == recipe_id).distinct()
    ).scalars())

    title_txt = " ".join(titles)
    ing_txt = " ".join(ing_names + tag_names)
    desc_txt = " ".join(d for d in descs if d)
    text_all = ing_svc.normalize(" ".join([title_txt, ing_txt]))

    session.execute(text("""
        INSERT INTO recipe_search (recipe_id, doc_simple, doc_english, text_all)
        VALUES (
            :id,
            setweight(to_tsvector('simple', :t), 'A') || setweight(to_tsvector('simple', :i), 'B')
                || setweight(to_tsvector('simple', :d), 'C'),
            setweight(to_tsvector('english', :t), 'A') || setweight(to_tsvector('english', :i), 'B')
                || setweight(to_tsvector('english', :d), 'C'),
            :all
        )
        ON CONFLICT (recipe_id) DO UPDATE SET
            doc_simple = EXCLUDED.doc_simple,
            doc_english = EXCLUDED.doc_english,
            text_all = EXCLUDED.text_all
    """), {"id": recipe_id, "t": ing_svc.normalize(title_txt), "i": ing_svc.normalize(ing_txt),
           "d": ing_svc.normalize(desc_txt), "all": text_all})


def tokens(q: str) -> list[str]:
    return [w for w in re.findall(r"\w+", ing_svc.normalize(q)) if len(w) >= 2]


def stem_prefix(word: str) -> str:
    """Drop likely inflection endings so the prefix query matches other forms."""
    if len(word) >= 6:
        return word[:-2]
    if len(word) == 5:
        return word[:-1]
    return word


@dataclass
class SearchResult:
    recipes: list[Recipe]
    unknown: list[str] = field(default_factory=list)  # filter names that matched no ingredient


def search(session: Session, q: str = "", has: list[str] | None = None,
           without: list[str] | None = None, limit: int = 200, category: str | None = None) -> SearchResult:
    has = [h for h in (has or []) if h.strip()]
    without = [w for w in (without or []) if w.strip()]
    where, params, rank = [], {}, ["0.0::float"]
    unknown: list[str] = []

    for i, tok in enumerate(tokens(q)):
        params[f"p{i}"] = f"{stem_prefix(tok)}:*"
        params[f"w{i}"] = tok
        alts = [
            f"s.doc_simple @@ to_tsquery('simple', :p{i})",
            f"s.doc_english @@ plainto_tsquery('english', :w{i})",
        ]
        if len(tok) >= 4:
            # Short words need a closer match ("salt" must not find "salat").
            alts.append(f"(:w{i} <% s.text_all AND word_similarity(:w{i}, s.text_all) >= "
                        f"{SHORT_WORD_THRESHOLD if len(tok) < 6 else TRIGRAM_THRESHOLD})")
            rank.append(f"word_similarity(:w{i}, s.text_all)")
        where.append("(" + " OR ".join(alts) + ")")
        rank += [f"ts_rank(s.doc_simple, to_tsquery('simple', :p{i}))",
                 f"ts_rank(s.doc_english, plainto_tsquery('english', :w{i}))"]

    if category:
        params["cat"] = category
        where.append("r.category = :cat")

    for i, name in enumerate(has):
        ids = ing_svc.match_for_filter(session, name)
        if not ids:
            unknown.append(name)
            ids = {-1}  # nothing can match
        params[f"h{i}"] = list(ids)
        where.append(f"EXISTS (SELECT 1 FROM recipe_ingredient ri WHERE ri.recipe_id = r.id "
                     f"AND ri.ingredient_id = ANY(:h{i}))")

    excluded: set[int] = set()
    for name in without:
        ids = ing_svc.match_for_filter(session, name)
        if not ids:
            unknown.append(name)
        excluded |= ids
    if excluded:
        params["x"] = list(excluded)
        where.append("NOT EXISTS (SELECT 1 FROM recipe_ingredient ri WHERE ri.recipe_id = r.id "
                     "AND ri.ingredient_id = ANY(:x))")

    session.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :t, true)"),
                    {"t": str(TRIGRAM_THRESHOLD)})
    sql = f"""
        SELECT r.id FROM recipe r
        LEFT JOIN recipe_search s ON s.recipe_id = r.id
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY ({" + ".join(rank)}) DESC, r.updated_at DESC
        LIMIT :limit
    """
    params["limit"] = limit
    ids = list(session.execute(text(sql), params).scalars())
    if not ids:
        return SearchResult([], unknown)
    recipes = session.execute(
        select(Recipe).where(Recipe.id.in_(ids)).options(
            selectinload(Recipe.tags),
            selectinload(Recipe.steps).selectinload(Step.photos),
        )
    ).scalars().all()
    order = {rid: n for n, rid in enumerate(ids)}
    return SearchResult(sorted(recipes, key=lambda r: order[r.id]), unknown)


def reindex_ingredient(session: Session, ingredient_id: int) -> None:
    """Re-index every recipe using an ingredient (after its names change)."""
    for rid in session.execute(
        select(RecipeIngredient.recipe_id).where(RecipeIngredient.ingredient_id == ingredient_id).distinct()
    ).scalars():
        reindex(session, rid)
