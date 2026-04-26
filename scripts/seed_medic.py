#!/usr/bin/env python3
"""
WorkMind v2 — MEDIC client seed script
Idempotent: safe to run multiple times.

Creates:
  • MEDIC organization  (id = 00000000-0000-0000-0000-000000000002)
  • 2 users: medic1@ideasito.it / medic2@ideasito.it  (with initial passwords)
  • 9 standard products (safety net — migration 0002 already seeds them)

Usage:
    docker compose exec workmind-api python scripts/seed_medic.py

    # Override passwords via env vars:
    MEDIC1_PASSWORD=xxx MEDIC2_PASSWORD=yyy docker compose exec workmind-api python scripts/seed_medic.py
"""
from __future__ import annotations

import hashlib
import os
import sys
import uuid

import psycopg2
from psycopg2.extras import register_uuid

# ── Config ────────────────────────────────────────────────────────────────────

MEDIC_ORG_ID   = "00000000-0000-0000-0000-000000000002"
MEDIC_ORG_SLUG = "medic"
MEDIC_ORG_NAME = "MEDIC Aesthetic Medicine"

USERS = [
    {
        "email": "medic1@ideasito.it",
        "display_name": "Medic Operatore 1",
        "role": "agent",
        "password_env": "MEDIC1_PASSWORD",
        "default_password": "Medic2024!",
    },
    {
        "email": "medic2@ideasito.it",
        "display_name": "Medic Operatore 2",
        "role": "agent",
        "password_env": "MEDIC2_PASSWORD",
        "default_password": "Medic2024!",
    },
]

PRODUCTS = [
    ("Juved",       "Juvederm — filler acido ialuronico",            "siringa"),
    ("Prophilo",    "Profhilo — bio-rimodellante acido ialuronico",   "siringa"),
    ("Vistabex",    "Vistabex — tossina botulinica tipo A",           "flacone"),
    ("Bocout",      "Bocouture — tossina botulinica tipo A",          "flacone"),
    ("Azalou",      "Azalow — skin booster acido ialuronico",         "siringa"),
    ("Flore",       "Flore — skin booster / biostimolante",           "siringa"),
    ("Crema anes",  "Crema anestetica topica",                        "tubo"),
    ("Prx",         "PRX-T33 — peeling chimico",                      "flacone"),
    ("Pqj",         "PQAge Junior — peeling chimico",                 "flacone"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _hash_password(plain: str) -> str:
    import bcrypt
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _get_conn() -> psycopg2.extensions.connection:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://workmind:workmind@postgres:5432/workmind",
    ).replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(database_url)


# ── Seed logic ────────────────────────────────────────────────────────────────

def seed(conn: psycopg2.extensions.connection) -> None:
    register_uuid()
    cur = conn.cursor()

    # ── 1. Organization ───────────────────────────────────────────────────────
    cur.execute(
        """
        INSERT INTO organizations (id, slug, name, sector, config_json)
        VALUES (%s, %s, %s, 'aesthetic_medicine', '{}')
        ON CONFLICT (id) DO NOTHING
        """,
        (MEDIC_ORG_ID, MEDIC_ORG_SLUG, MEDIC_ORG_NAME),
    )
    print(f"[org]  {MEDIC_ORG_SLUG} — {'inserted' if cur.rowcount else 'already exists'}")

    # ── 2. Users ──────────────────────────────────────────────────────────────
    for u in USERS:
        user_id      = str(uuid.uuid4())
        email        = u["email"]
        ehash        = _email_hash(email)
        plain_pw     = os.getenv(u["password_env"], u["default_password"])
        pw_hash      = _hash_password(plain_pw)

        cur.execute(
            """
            INSERT INTO users (id, org_id, email, email_hash, display_name, role, is_active, password_hash)
            VALUES (%s, %s, %s, %s, %s, %s, true, %s)
            ON CONFLICT ON CONSTRAINT uq_users_org_email DO UPDATE
                SET display_name  = EXCLUDED.display_name,
                    role          = EXCLUDED.role,
                    org_id        = EXCLUDED.org_id,
                    password_hash = EXCLUDED.password_hash
            """,
            (user_id, MEDIC_ORG_ID, email, ehash, u["display_name"], u["role"], pw_hash),
        )
        print(f"[user] {email} ({u['role']}) — upserted  [password: {plain_pw}]")

    # ── 3. Products (safety net — migration 0002 already seeds them) ──────────
    for name, description, unit in PRODUCTS:
        cur.execute(
            """
            INSERT INTO medic_products (org_id, name, description, unit, stock_qty)
            VALUES (%s, %s, %s, %s, 0)
            ON CONFLICT ON CONSTRAINT uq_medic_products_org_name DO NOTHING
            """,
            (MEDIC_ORG_ID, name, description, unit),
        )
        if cur.rowcount:
            print(f"[prod] {name} — inserted")

    conn.commit()
    cur.close()
    print("\n✓ Seed MEDIC completato.")
    print("\nCredenziali di accesso:")
    for u in USERS:
        pw = os.getenv(u["password_env"], u["default_password"])
        print(f"  {u['email']}  /  {pw}")
    print("\nCAMBIARE le password alla prima sessione produzione!")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        conn = _get_conn()
    except Exception as exc:
        print(f"ERROR: impossibile connettersi al database — {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        seed(conn)
    except Exception as exc:
        conn.rollback()
        print(f"ERROR durante seed: {exc}", file=sys.stderr)
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()
