"""admin flag on users

Revision ID: 0008
Revises: 0007
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
    # Everyone so far was added from the console, which now means admin.
    op.execute("UPDATE app_user SET is_admin = true")


def downgrade() -> None:
    op.drop_column("app_user", "is_admin")
