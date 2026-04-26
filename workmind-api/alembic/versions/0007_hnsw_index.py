"""Add HNSW vector index on document_chunks.embedding for fast similarity search.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        """
        CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS idx_chunks_embedding_hnsw"))
