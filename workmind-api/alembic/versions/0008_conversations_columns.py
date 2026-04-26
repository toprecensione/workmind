"""Add channel_type and metadata_json to conversations table.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-22
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Store channel_type as varchar (consistent with channels table)
    op.add_column(
        "conversations",
        sa.Column("channel_type", sa.String(32), nullable=False, server_default="web"),
    )
    op.add_column(
        "conversations",
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("conversations", "metadata_json")
    op.drop_column("conversations", "channel_type")
