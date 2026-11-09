from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint, false, func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

LANG = String(8)


class Recipe(Base):
    __tablename__ = "recipe"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    servings: Mapped[int | None] = mapped_column(Integer)
    original_lang: Mapped[str] = mapped_column(LANG, default="is")
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeIngredient.position"
    )
    items: Mapped[list["RecipeItem"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeItem.position"
    )
    steps: Mapped[list["Step"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="Step.position"
    )
    tags: Mapped[list["Tag"]] = relationship(secondary="recipe_tag", order_by="Tag.id")
    translations: Mapped[list["RecipeTranslation"]] = relationship(cascade="all, delete-orphan")


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    names: Mapped[list["TagName"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class TagName(Base):
    __tablename__ = "tag_name"
    __table_args__ = (UniqueConstraint("lang", "norm"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), index=True)
    lang: Mapped[str] = mapped_column(LANG)
    name: Mapped[str] = mapped_column(Text)
    norm: Mapped[str] = mapped_column(Text)


class RecipeTag(Base):
    __tablename__ = "recipe_tag"

    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True)


class Ingredient(Base):
    """Canonical ingredient. Names (per language, with aliases) live in IngredientName."""

    __tablename__ = "ingredient"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Groups: "almond" -> "nuts", so "without nuts" excludes almonds.
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("ingredient.id", ondelete="SET NULL"))
    # Id in the external food database (nutrition phase).
    food_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    names: Mapped[list["IngredientName"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="IngredientName.id"
    )
    parent: Mapped["Ingredient | None"] = relationship(remote_side=[id])

    def name_in(self, lang: str) -> str:
        """Primary name in lang, else any primary, else any name."""
        for pref in (
            lambda n: n.lang == lang and n.is_primary,
            lambda n: n.lang == lang,
            lambda n: n.is_primary,
            lambda n: True,
        ):
            for n in self.names:
                if pref(n):
                    return n.name
        return ""


class IngredientName(Base):
    __tablename__ = "ingredient_name"
    __table_args__ = (
        UniqueConstraint("lang", "norm"),
        Index("ix_ingredient_name_norm_trgm", "norm", postgresql_using="gin",
              postgresql_ops={"norm": "gin_trgm_ops"}),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id", ondelete="CASCADE"), index=True)
    lang: Mapped[str] = mapped_column(LANG)
    name: Mapped[str] = mapped_column(Text)
    norm: Mapped[str] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredient"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"), index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # Optional group heading, e.g. "Deig" / "Sveskjumauk". Consecutive rows with the
    # same section are shown under one heading. Empty = no heading.
    section: Mapped[str] = mapped_column(Text, default="", server_default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Nutrition phase: per-row match to the food database.
    food_id: Mapped[str | None] = mapped_column(Text)
    match_confidence: Mapped[float | None] = mapped_column(Float)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
    ingredient: Mapped[Ingredient] = relationship(lazy="joined")


class RecipeItem(Base):
    """Optional "you'll need" implements."""

    __tablename__ = "recipe_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)

    recipe: Mapped[Recipe] = relationship(back_populates="items")


class Step(Base):
    __tablename__ = "step"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")

    recipe: Mapped[Recipe] = relationship(back_populates="steps")
    photos: Mapped[list["StepPhoto"]] = relationship(
        cascade="all, delete-orphan", order_by="StepPhoto.position", lazy="selectin"
    )


class StepPhoto(Base):
    __tablename__ = "step_photo"

    id: Mapped[int] = mapped_column(primary_key=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("step.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(Text)  # relative to PHOTOS_DIR
    position: Mapped[int] = mapped_column(Integer, default=0)
    caption: Mapped[str] = mapped_column(Text, default="")


# --- Content translations (filled by the LLM phase; editable by the user) ---

class RecipeTranslation(Base):
    __tablename__ = "recipe_translation"

    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True)
    lang: Mapped[str] = mapped_column(LANG, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    is_machine: Mapped[bool] = mapped_column(Boolean, default=True)
    # Hash of the original text when translated; mismatch = stale translation.
    source_hash: Mapped[str | None] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StepTranslation(Base):
    __tablename__ = "step_translation"

    step_id: Mapped[int] = mapped_column(ForeignKey("step.id", ondelete="CASCADE"), primary_key=True)
    lang: Mapped[str] = mapped_column(LANG, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    is_machine: Mapped[bool] = mapped_column(Boolean, default=True)
    source_hash: Mapped[str | None] = mapped_column(Text)


class RecipeItemTranslation(Base):
    __tablename__ = "recipe_item_translation"

    item_id: Mapped[int] = mapped_column(ForeignKey("recipe_item.id", ondelete="CASCADE"), primary_key=True)
    lang: Mapped[str] = mapped_column(LANG, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    is_machine: Mapped[bool] = mapped_column(Boolean, default=True)
    source_hash: Mapped[str | None] = mapped_column(Text)


class RecipeIngredientTranslation(Base):
    __tablename__ = "recipe_ingredient_translation"

    recipe_ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("recipe_ingredient.id", ondelete="CASCADE"), primary_key=True
    )
    lang: Mapped[str] = mapped_column(LANG, primary_key=True)
    note: Mapped[str] = mapped_column(Text)
    section: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_machine: Mapped[bool] = mapped_column(Boolean, default=True)
    source_hash: Mapped[str | None] = mapped_column(Text)


# --- Search (rebuilt by app/services/search.py on every save) ---

class RecipeSearch(Base):
    __tablename__ = "recipe_search"
    __table_args__ = (
        Index("ix_recipe_search_simple", "doc_simple", postgresql_using="gin"),
        Index("ix_recipe_search_english", "doc_english", postgresql_using="gin"),
        Index("ix_recipe_search_text_trgm", "text_all", postgresql_using="gin",
              postgresql_ops={"text_all": "gin_trgm_ops"}),
    )

    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True)
    doc_simple = mapped_column(TSVECTOR, nullable=False)
    doc_english = mapped_column(TSVECTOR, nullable=False)
    text_all: Mapped[str] = mapped_column(Text, default="")


# --- Later phases: schema in place now ---

class RecipeNutrition(Base):
    __tablename__ = "recipe_nutrition"
    __table_args__ = (
        CheckConstraint("status IN ('pending','running','complete','incomplete','failed')"),
    )

    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True)
    servings: Mapped[int | None] = mapped_column(Integer)
    per_portion: Mapped[dict | None] = mapped_column(JSONB)
    per_dish: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportDraft(Base):
    """A recipe being imported from a URL or pasted text. Never a Recipe until the
    user reviews and saves it."""

    __tablename__ = "import_draft"
    __table_args__ = (
        CheckConstraint("status IN ('pending','fetching','extracting','ready','failed','saved')"),
        CheckConstraint("kind IN ('url','text','image')", name="import_draft_kind_check"),
        Index("ix_import_draft_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), default="url")
    url: Mapped[str | None] = mapped_column(Text)
    source_text: Mapped[str | None] = mapped_column(Text)  # pasted, or extracted from the page
    images: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")  # paths under PHOTOS_DIR
    instructions: Mapped[str] = mapped_column(Text, default="", server_default="")  # user's directions to the LLM
    status: Mapped[str] = mapped_column(String(16), default="pending")
    raw: Mapped[dict | None] = mapped_column(JSONB)  # scraper metadata
    draft: Mapped[dict | None] = mapped_column(JSONB)  # RecipeIn-shaped
    events: Mapped[list] = mapped_column(JSONB, default=list)  # progress, from tool calls
    detected_lang: Mapped[str | None] = mapped_column(LANG)
    error: Mapped[str | None] = mapped_column(Text)
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipe.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )



class AppUser(Base):
    """A household member who can log in. Users added from the console are admins;
    admins add the others at /admin."""

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True)


class UserSession(Base):
    """A logged-in browser. Never expires; revoked by logging out or from Settings.
    Only a SHA-256 of the cookie token is stored."""

    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_agent: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[AppUser] = relationship(back_populates="sessions")
