"""kb_agents: resize embeddings to 768, HNSW indexes, kb_watch_paths table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Resize vector columns 1536 → 768 ──────────────────────────────────
    # Drop existing vector indexes first (if any), then alter column type.
    # These run inside the Alembic transaction (that's fine for ALTER COLUMN).
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(768) USING NULL::vector(768)")
    op.execute("ALTER TABLE memories ALTER COLUMN embedding TYPE vector(768) USING NULL::vector(768)")

    # ── 2. HNSW indexes for cosine similarity ────────────────────────────────
    # CREATE INDEX CONCURRENTLY *cannot* run inside a transaction.
    # We use Alembic's autocommit_block() to step outside the transaction for
    # these two statements, then resume normal transactional mode for the rest.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_embedding "
            "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memories_embedding "
            "ON memories USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )

    # ── 3. kb_watch_paths table ───────────────────────────────────────────────
    op.create_table(
        'kb_watch_paths',
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
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column(
            'path_type',
            sa.String(16),
            nullable=False,
            server_default='local',
        ),
        sa.Column('smb_config_enc', sa.Text(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_scan_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index('idx_kb_watch_paths_org', 'kb_watch_paths', ['org_id'])

    # ── 4. allowed_roles column on connectors (missing from 0003) ─────────────
    # Add if missing; use try/except-style conditional via DO block
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='connectors' AND column_name='allowed_roles'
            ) THEN
                ALTER TABLE connectors ADD COLUMN allowed_roles jsonb;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_index('idx_kb_watch_paths_org', table_name='kb_watch_paths')
    op.drop_table('kb_watch_paths')

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_memories_embedding")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chunks_embedding")

    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1536) USING NULL::vector(1536)")
    op.execute("ALTER TABLE memories ALTER COLUMN embedding TYPE vector(1536) USING NULL::vector(1536)")
