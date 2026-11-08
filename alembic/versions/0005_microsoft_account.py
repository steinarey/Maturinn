"""microsoft account (To Do shopping list)

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "microsoft_account",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.Text()),
        sa.Column("token_cache", sa.Text()),
        sa.Column("auth_flow", sa.Text()),
        sa.Column("list_id", sa.Text()),
        sa.Column("list_name", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="microsoft_account_single_row"),
    )


def downgrade() -> None:
    op.drop_table("microsoft_account")
