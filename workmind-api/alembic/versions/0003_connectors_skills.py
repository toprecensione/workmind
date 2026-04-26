"""connectors and skills tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'connectors',
        sa.Column('id',         postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id',     postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type',       sa.String(50),  nullable=False),
        sa.Column('name',       sa.String(200), nullable=False, server_default=''),
        sa.Column('is_enabled', sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('config_enc', sa.Text(),      nullable=True),
        sa.Column('status',     sa.String(20),  nullable=False, server_default='unconfigured'),
        sa.Column('status_msg', sa.Text(),      nullable=True),
        sa.Column('tested_at',  sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('org_id', 'type', name='uq_connectors_org_type'),
    )
    op.create_table(
        'skills',
        sa.Column('id',          postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id',      postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('skill_id',    sa.String(100), nullable=False),
        sa.Column('is_enabled',  sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('config_json', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at',  sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('org_id', 'skill_id', name='uq_skills_org_skill'),
    )


def downgrade() -> None:
    op.drop_table('skills')
    op.drop_table('connectors')
