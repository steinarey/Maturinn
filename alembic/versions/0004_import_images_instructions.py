"""import images and instructions

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("import_draft", sa.Column("images", postgresql.JSONB(astext_type=sa.Text()),
                                            server_default="[]", nullable=False))
    op.add_column("import_draft", sa.Column("instructions", sa.Text(), server_default="", nullable=False))
    op.drop_constraint("import_draft_kind_check", "import_draft", type_="check")
    op.create_check_constraint("import_draft_kind_check", "import_draft", "kind IN ('url','text','image')")


def downgrade() -> None:
    op.execute("DELETE FROM import_draft WHERE kind = 'image'")
    op.drop_constraint("import_draft_kind_check", "import_draft", type_="check")
    op.create_check_constraint("import_draft_kind_check", "import_draft", "kind IN ('url','text')")
    op.drop_column("import_draft", "instructions")
    op.drop_column("import_draft", "images")
