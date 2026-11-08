"""Canonical ingredient names: normalization, lookup, creation, merging.

Every recipe row links to one canonical `ingredient`. An ingredient has any
number of names per language (one primary per language, the rest aliases),
so "chicken breast", "chicken breasts", "chicken fillet" and
"kjúklingabringa" can all point at the same row.
"""
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.models import Ingredient, IngredientName, RecipeIngredient

_EDGE_PUNCT = " \t\n.,;:!?()[]{}\"'«»„“”-–—*"


def normalize(name: str) -> str:
    """Casefold, NFC, collapse whitespace, trim punctuation. Keeps þ/ð/æ/ö/á etc."""
    s = unicodedata.normalize("NFC", name or "").casefold()
    s = re.sub(r"\s+", " ", s).strip(_EDGE_PUNCT)
    return s


def _singular_en(word: str) -> list[str]:
    out = []
    if len(word) > 4 and word.endswith("ies"):
        out.append(word[:-3] + "y")  # berries -> berry
    if len(word) > 4 and word.endswith("oes"):
        out.append(word[:-2])  # tomatoes -> tomato
    if len(word) > 4 and re.search(r"(ches|shes|xes|sses|zes)$", word):
        out.append(word[:-2])  # peaches -> peach
    if len(word) > 4 and word.endswith("ves"):
        out += [word[:-3] + "f", word[:-3] + "fe"]  # leaves -> leaf, knives -> knife
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        out.append(word[:-1])  # breasts -> breast
    return out


def candidates(norm: str) -> list[str]:
    """The name plus naive English singular forms of its last word."""
    if not norm:
        return []
    head, _, last = norm.rpartition(" ")
    prefix = f"{head} " if head else ""
    return [norm] + [prefix + w for w in _singular_en(last)]


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def is_inflection(a: str, b: str) -> bool:
    """Conservative guess that a and b are the same word with different endings.

    Icelandic inflects by changing endings (kjúklingabringa / kjúklingabringur).
    Only long shared stems count, so "salt"/"salat" and "pear"/"pearl" don't match.
    """
    if a == b:
        return True
    shorter = min(len(a), len(b))
    p = _common_prefix(a, b)
    return shorter >= 5 and p >= 4 and p >= shorter - 2 and abs(len(a) - len(b)) <= 3


def find(session: Session, name: str) -> Ingredient | None:
    """Exact or English-singular match on any language's names."""
    cands = candidates(normalize(name))
    if not cands:
        return None
    row = session.execute(
        select(IngredientName.ingredient_id)
        .where(IngredientName.norm.in_(cands))
        .order_by((IngredientName.norm == cands[0]).desc(), IngredientName.is_primary.desc())
        .limit(1)
    ).scalar()
    return session.get(Ingredient, row) if row else None


def find_inflected(session: Session, name: str) -> Ingredient | None:
    """Fallback for inflected forms: trigram candidates filtered by is_inflection."""
    norm = normalize(name)
    if len(norm) < 5:
        return None
    rows = session.execute(
        select(IngredientName.ingredient_id, IngredientName.norm)
        .where(IngredientName.norm.op("%")(norm))
        .order_by(func.similarity(IngredientName.norm, norm).desc())
        .limit(10)
    ).all()
    for ing_id, other in rows:
        if is_inflection(norm, other):
            return session.get(Ingredient, ing_id)
    return None


@dataclass
class Suggestion:
    ingredient_id: int
    name: str
    lang: str
    score: float


def suggest(session: Session, name: str, limit: int = 6) -> list[Suggestion]:
    """Names similar to `name` (prefix or trigram), best first."""
    norm = normalize(name)
    if not norm:
        return []
    sim = func.greatest(func.similarity(IngredientName.norm, norm), func.word_similarity(norm, IngredientName.norm))
    rows = session.execute(
        select(IngredientName.ingredient_id, IngredientName.name, IngredientName.lang, sim.label("score"))
        .where((IngredientName.norm.startswith(norm, autoescape=True)) | (sim > 0.3))
        .order_by(IngredientName.norm.startswith(norm, autoescape=True).desc(), sim.desc())
        .limit(limit * 2)
    ).all()
    seen, out = set(), []
    for ing_id, nm, lang, score in rows:
        if ing_id in seen:
            continue
        seen.add(ing_id)
        out.append(Suggestion(ing_id, nm, lang, float(score)))
    return out[:limit]


def resolve(session: Session, name: str, lang: str) -> tuple[Ingredient, bool]:
    """Find the canonical ingredient for a name, or create it. Returns (ingredient, created)."""
    ing = find(session, name) or find_inflected(session, name)
    if ing:
        return ing, False
    ing = Ingredient()
    ing.names.append(IngredientName(lang=lang, name=name.strip(), norm=normalize(name), is_primary=True))
    session.add(ing)
    session.flush()
    return ing, True


class NameConflict(ValueError):
    pass


def set_names(session: Session, ing: Ingredient, lang: str, primary: str, aliases: list[str]) -> None:
    """Replace this ingredient's names in one language."""
    wanted: list[tuple[str, bool]] = []
    seen = set()
    for nm, is_primary in [(primary, True)] + [(a, False) for a in aliases]:
        n = normalize(nm)
        if n and n not in seen:
            seen.add(n)
            wanted.append((nm.strip(), is_primary))
    norms = [normalize(n) for n, _ in wanted]
    if norms:
        clash = session.execute(
            select(IngredientName.name)
            .where(IngredientName.lang == lang, IngredientName.norm.in_(norms),
                   IngredientName.ingredient_id != ing.id)
        ).scalars().first()
        if clash:
            raise NameConflict(clash)
    for n in [n for n in ing.names if n.lang == lang]:
        ing.names.remove(n)
    session.flush()
    for nm, is_primary in wanted:
        ing.names.append(IngredientName(lang=lang, name=nm, norm=normalize(nm), is_primary=is_primary))
    session.flush()


def merge(session: Session, source: Ingredient, target: Ingredient) -> None:
    """Fold `source` into `target`: recipe rows, names (as aliases) and children move over."""
    if source.id == target.id:
        return
    session.execute(
        update(RecipeIngredient).where(RecipeIngredient.ingredient_id == source.id)
        .values(ingredient_id=target.id)
    )
    session.execute(update(Ingredient).where(Ingredient.parent_id == source.id).values(parent_id=target.id))
    existing = {(n.lang, n.norm) for n in target.names}
    moved = [(n.lang, n.name, n.norm) for n in source.names if (n.lang, n.norm) not in existing]
    if target.food_id is None:
        target.food_id = source.food_id
    session.delete(source)
    session.flush()
    for lang, nm, norm in moved:
        target.names.append(IngredientName(lang=lang, name=nm, norm=norm, is_primary=False))
    session.flush()


def with_descendants(session: Session, ids: set[int]) -> set[int]:
    """The given ingredients plus everything grouped under them (any depth)."""
    if not ids:
        return set()
    rows = session.execute(
        text("""
            WITH RECURSIVE tree(id) AS (
                SELECT id FROM ingredient WHERE id = ANY(:ids)
                UNION
                SELECT i.id FROM ingredient i JOIN tree t ON i.parent_id = t.id
            )
            SELECT id FROM tree
        """),
        {"ids": list(ids)},
    ).scalars()
    return set(rows)


def match_for_filter(session: Session, name: str) -> set[int]:
    """Ingredient ids a search filter like "has chicken" refers to.

    Exact/singular name match, plus names containing the term as a whole word
    ("chicken" -> "chicken thigh"), plus a conservative inflection match.
    Groups expand to their members.
    """
    norm = normalize(name)
    if not norm:
        return set()
    ids: set[int] = set()
    ing = find(session, norm)
    if ing:
        ids.add(ing.id)
    for cand in candidates(norm):
        ids |= set(session.execute(
            select(IngredientName.ingredient_id)
            .where(IngredientName.norm.regexp_match(r"(^|\s)" + re.escape(cand) + r"($|\s)"))
        ).scalars())
    if not ids:
        ing = find_inflected(session, norm)
        if ing:
            ids.add(ing.id)
    return with_descendants(session, ids)
