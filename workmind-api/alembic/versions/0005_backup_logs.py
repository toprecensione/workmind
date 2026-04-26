"""backup_logs: table for pg_dump backup audit trail

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-18
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'backup_logs',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            'org_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('filename', sa.String(256), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column(
            'status',
            sa.String(20),
            nullable=False,
            server_default='pending',
        ),
        sa.Column('error_msg', sa.Text(), nullable=True),
        sa.Column('duration_s', sa.Integer(), nullable=True),
        sa.Column(
            'triggered_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'idx_backup_logs_org_created',
        'backup_logs',
        ['org_id', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('idx_backup_logs_org_created', table_name='backup_logs')
    op.drop_table('backup_logs')
