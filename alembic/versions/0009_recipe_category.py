"""optional recipe category

Revision ID: 0009
Revises: 0008
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A code from app/categories.py (no DB enum, so adding a category needs no migration).
    op.add_column("recipe", sa.Column("category", sa.Text(), nullable=True))
    op.create_index("ix_recipe_category", "recipe", ["category"])


def downgrade() -> None:
    op.drop_index("ix_recipe_category", table_name="recipe")
    op.drop_column("recipe", "category")
