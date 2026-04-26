"""
WorkMind — Phase 0 Data Migration Script
Migrates legacy JSON data files to PostgreSQL.

Sources:
  - knowledge_base.json       → documents + document_chunks (pending re-index)
  - whatsapp_conversations.json → conversations + messages
  - audit_trail.jsonl         → audit_logs
  - budget_usage.json         → model_usage (historical)
  - chat_*.json               → conversations + messages (web channel)

Usage:
  python scripts/seed_from_json.py --source-dir ./data --dry-run
  python scripts/seed_from_json.py --source-dir ./data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_ORG_SLUG = "default"


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate WorkMind v1 JSON data to PostgreSQL")
    parser.add_argument("--source-dir", required=True, help="Path to data directory")
    parser.add_argument("--database-url", help="PostgreSQL URL (overrides DATABASE_URL env var)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without writing")
    args = parser.parse_args()

    import os
    db_url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set. Use --database-url or set DATABASE_URL env var.")
        sys.exit(1)

    # Normalize to sync psycopg2 URL for migration script
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    source_dir = Path(args.source_dir)
    if not source_dir.exists():
        print(f"ERROR: Source directory not found: {source_dir}")
        sys.exit(1)

    print(f"WorkMind v1 → v2 Data Migration")
    print(f"Source: {source_dir}")
    print(f"Target: {db_url.split('@')[1] if '@' in db_url else db_url}")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    if args.dry_run:
        print("DRY RUN MODE — no data will be written\n")

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    if not args.dry_run:
        engine = create_engine(db_url, pool_pre_ping=True)
        Session = sessionmaker(bind=engine)
        db = Session()
    else:
        db = None

    try:
        _migrate_knowledge_base(source_dir, db, args.dry_run)
        _migrate_whatsapp_conversations(source_dir, db, args.dry_run)
        _migrate_chat_history(source_dir, db, args.dry_run)
        _migrate_audit_trail(source_dir, db, args.dry_run)

        if db and not args.dry_run:
            db.commit()
            print("\nAll migrations committed successfully.")

    except Exception as exc:
        if db:
            db.rollback()
        print(f"\nERROR during migration: {exc}")
        raise
    finally:
        if db:
            db.close()


def _migrate_knowledge_base(source_dir: Path, db, dry_run: bool) -> None:
    """Migrate knowledge_base.json to documents table."""
    kb_file = source_dir / "knowledge_base.json"
    if not kb_file.exists():
        print(f"[kb] knowledge_base.json not found — skipping")
        return

    with open(kb_file, encoding="utf-8") as f:
        kb_data = json.load(f)

    entries = kb_data if isinstance(kb_data, list) else kb_data.get("entries", [])
    print(f"[kb] Found {len(entries)} knowledge base entries")

    if dry_run:
        for i, entry in enumerate(entries[:3]):
            print(f"  [{i}] {str(entry)[:80]}...")
        return

    from sqlalchemy import text
    for entry in entries:
        content = entry.get("content", "") or entry.get("text", "") or str(entry)
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # Check for duplicates
        existing = db.execute(
            text("SELECT id FROM documents WHERE content_hash = :h"),
            {"h": content_hash}
        ).fetchone()

        if not existing:
            doc_id = uuid.uuid4()
            db.execute(text("""
                INSERT INTO documents (id, org_id, filename, content_hash, status, metadata_json)
                VALUES (:id, :org_id, :filename, :hash, 'pending', :meta)
            """), {
                "id": doc_id,
                "org_id": DEFAULT_ORG_ID,
                "filename": f"kb_{doc_id.hex[:8]}.txt",
                "hash": content_hash,
                "meta": json.dumps({"raw_content": content, "source": "knowledge_base_v1", **{k: v for k, v in entry.items() if k not in ("content", "text")}}),
            })

    print(f"[kb] Migrated {len(entries)} entries (pending re-index)")


def _migrate_whatsapp_conversations(source_dir: Path, db, dry_run: bool) -> None:
    """Migrate whatsapp_conversations.json to conversations + messages."""
    wa_file = source_dir / "whatsapp_conversations.json"
    if not wa_file.exists():
        print(f"[wa] whatsapp_conversations.json not found — skipping")
        return

    with open(wa_file, encoding="utf-8") as f:
        wa_data = json.load(f)

    conversations = wa_data if isinstance(wa_data, list) else wa_data.get("conversations", [])
    print(f"[wa] Found {len(conversations)} WhatsApp conversations")

    if dry_run:
        return

    _migrate_conversation_list(conversations, "whatsapp", db)


def _migrate_chat_history(source_dir: Path, db, dry_run: bool) -> None:
    """Migrate chat_*.json files to conversations + messages."""
    chat_files = list(source_dir.glob("chat_*.json"))
    print(f"[chat] Found {len(chat_files)} chat history files")

    if dry_run or not chat_files:
        return

    for chat_file in chat_files:
        try:
            with open(chat_file, encoding="utf-8") as f:
                messages = json.load(f)
            if messages:
                _migrate_conversation_list([{"messages": messages, "source": chat_file.name}], "web", db)
        except Exception as exc:
            print(f"[chat] Warning: could not migrate {chat_file.name}: {exc}")


def _migrate_conversation_list(conversations: list, channel_type: str, db) -> None:
    """Generic conversation migration."""
    from sqlalchemy import text
    migrated = 0
    for conv_data in conversations:
        conv_id = uuid.uuid4()
        messages = conv_data.get("messages", [])
        if not messages:
            continue

        first_msg = next((m.get("content", m.get("message", "")) for m in messages if m.get("role") == "user"), "")
        title = first_msg[:100] if first_msg else None

        db.execute(text("""
            INSERT INTO conversations (id, org_id, channel_type, title, metadata_json)
            VALUES (:id, :org_id, :channel, :title, :meta)
        """), {
            "id": conv_id,
            "org_id": DEFAULT_ORG_ID,
            "channel": channel_type,
            "title": title,
            "meta": json.dumps({"migrated_from": "v1", "source": conv_data.get("source", "unknown")}),
        })

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", msg.get("message", msg.get("text", "")))
            if not content:
                continue
            db.execute(text("""
                INSERT INTO messages (id, conversation_id, role, content, metadata_json)
                VALUES (:id, :conv_id, :role, :content, '{}')
            """), {
                "id": uuid.uuid4(),
                "conv_id": conv_id,
                "role": role if role in ("user", "assistant", "system", "tool") else "user",
                "content": content,
            })

        migrated += 1

    print(f"  [{channel_type}] Migrated {migrated} conversations")


def _migrate_audit_trail(source_dir: Path, db, dry_run: bool) -> None:
    """Migrate audit_trail.jsonl to audit_logs."""
    audit_file = source_dir / "audit_trail.jsonl"
    if not audit_file.exists():
        print(f"[audit] audit_trail.jsonl not found — skipping")
        return

    from sqlalchemy import text
    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    print(f"[audit] Found {len(lines)} audit log entries")

    if dry_run:
        return

    migrated = 0
    for line in lines:
        try:
            entry = json.loads(line)
            db.execute(text("""
                INSERT INTO audit_logs (org_id, event_type, actor, summary, details_json)
                VALUES (:org_id, 'ai_decision', :actor, :summary, :details)
            """), {
                "org_id": DEFAULT_ORG_ID,
                "actor": entry.get("actor", "system"),
                "summary": entry.get("summary", entry.get("message", "Migrated from v1"))[:512],
                "details": json.dumps(entry),
            })
            migrated += 1
        except Exception as exc:
            pass  # skip malformed lines

    print(f"[audit] Migrated {migrated} entries")


if __name__ == "__main__":
    main()
