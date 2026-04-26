"""align_schema: fix documents/memories/model_usage column mismatches

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── documents: add columns missing from initial schema ────────────────────
    # Add user_id FK (nullable)
    op.execute("""
        ALTER TABLE documents
        ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL
    """)
    # Add filename (copy from title for existing rows, then make it a proper column)
    op.execute("""
        ALTER TABLE documents
        ADD COLUMN IF NOT EXISTS filename VARCHAR(512)
    """)
    op.execute("""
        UPDATE documents SET filename = title WHERE filename IS NULL
    """)
    # Add mime_type (nullable)
    op.execute("""
        ALTER TABLE documents
        ADD COLUMN IF NOT EXISTS mime_type VARCHAR(128)
    """)
    # Add source_path (nullable)
    op.execute("""
        ALTER TABLE documents
        ADD COLUMN IF NOT EXISTS source_path TEXT
    """)
    # Add total_chunks (integer, default 0)
    op.execute("""
        ALTER TABLE documents
        ADD COLUMN IF NOT EXISTS total_chunks INTEGER NOT NULL DEFAULT 0
    """)
    # Rename meta_json → metadata_json (or add alias)
    # We add metadata_json and copy from meta_json, then keep both for compatibility
    op.execute("""
        ALTER TABLE documents
        ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
    """)
    op.execute("""
        UPDATE documents SET metadata_json = meta_json WHERE metadata_json = '{}'::jsonb
    """)

    # ── documents: fix status column (VARCHAR, not PG enum) ──────────────────
    # The status column exists as VARCHAR in DB, no change needed for storage.
    # SQLAlchemy model uses Enum(DocumentStatus) which generates ::document_status
    # cast — this is handled in Python layer by using .value comparisons.

    # ── memories: add is_active flag ─────────────────────────────────────────
    op.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true
    """)

    # ── memories: add metadata_json ──────────────────────────────────────────
    op.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
    """)

    # ── model_usage: align with current model ────────────────────────────────
    # DB has: model, tokens_in, tokens_out (from 0001)
    # Model expects: model_name, input_tokens, output_tokens, recorded_at
    op.execute("""
        ALTER TABLE model_usage
        ADD COLUMN IF NOT EXISTS model_name VARCHAR(128)
    """)
    op.execute("""
        UPDATE model_usage SET model_name = model WHERE model_name IS NULL
    """)
    op.execute("""
        ALTER TABLE model_usage
        ADD COLUMN IF NOT EXISTS input_tokens INTEGER NOT NULL DEFAULT 0
    """)
    op.execute("""
        UPDATE model_usage SET input_tokens = tokens_in WHERE input_tokens = 0
    """)
    op.execute("""
        ALTER TABLE model_usage
        ADD COLUMN IF NOT EXISTS output_tokens INTEGER NOT NULL DEFAULT 0
    """)
    op.execute("""
        UPDATE model_usage SET output_tokens = tokens_out WHERE output_tokens = 0
    """)
    op.execute("""
        ALTER TABLE model_usage
        ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ
    """)
    op.execute("""
        UPDATE model_usage SET recorded_at = created_at WHERE recorded_at IS NULL
    """)
    # Add success, error_code, latency_ms, conversation_id, message_id
    op.execute("""
        ALTER TABLE model_usage
        ADD COLUMN IF NOT EXISTS latency_ms INTEGER
    """)
    op.execute("""
        ALTER TABLE model_usage
        ADD COLUMN IF NOT EXISTS success BOOLEAN NOT NULL DEFAULT true
    """)
    op.execute("""
        ALTER TABLE model_usage
        ADD COLUMN IF NOT EXISTS error_code VARCHAR(64)
    """)
    op.execute("""
        ALTER TABLE model_usage
        ADD COLUMN IF NOT EXISTS conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL
    """)
    op.execute("""
        ALTER TABLE model_usage
        ADD COLUMN IF NOT EXISTS message_id UUID REFERENCES messages(id) ON DELETE SET NULL
    """)
    # model_role: already exists as varchar, no change needed
    # provider: exists as varchar, no change needed

    # ── document_chunks: add org_id if missing ───────────────────────────────
    op.execute("""
        ALTER TABLE document_chunks
        ADD COLUMN IF NOT EXISTS org_id UUID REFERENCES organizations(id) ON DELETE CASCADE
    """)
    # Backfill org_id from parent document
    op.execute("""
        UPDATE document_chunks dc
        SET org_id = d.org_id
        FROM documents d
        WHERE dc.document_id = d.id AND dc.org_id IS NULL
    """)


def downgrade() -> None:
    # Remove added columns (reverse order)
    for col in ["message_id", "conversation_id", "error_code", "success",
                "latency_ms", "recorded_at", "output_tokens", "input_tokens", "model_name"]:
        op.execute(f"ALTER TABLE model_usage DROP COLUMN IF EXISTS {col}")

    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS metadata_json")
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS is_active")

    for col in ["metadata_json", "total_chunks", "source_path", "mime_type", "filename", "user_id"]:
        op.execute(f"ALTER TABLE documents DROP COLUMN IF EXISTS {col}")
