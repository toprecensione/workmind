"""MEDIC client schema — products, inventory lots, sales

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-09 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

MEDIC_ORG_ID = "00000000-0000-0000-0000-000000000002"


def upgrade() -> None:

    # ── MEDIC organization ────────────────────────────────────────────────────
    op.execute(f"""
        INSERT INTO organizations (id, slug, name, sector, config_json)
        VALUES (
            '{MEDIC_ORG_ID}',
            'medic',
            'MEDIC Aesthetic Medicine',
            'aesthetic_medicine',
            '{{}}'
        )
        ON CONFLICT (id) DO NOTHING
    """)

    # Create set_updated_at trigger function (if not exists)
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ── medic_products ────────────────────────────────────────────────────────
    op.create_table(
        "medic_products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("unit", sa.String(32), nullable=False, server_default="piece"),
        sa.Column("price_eur", sa.Numeric(10, 2)),
        sa.Column("stock_qty", sa.Integer, nullable=False, server_default="0"),
        sa.Column("low_stock_threshold", sa.Integer, server_default="5"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.UniqueConstraint("org_id", "name", name="uq_medic_products_org_name"),
        sa.CheckConstraint("stock_qty >= 0", name="ck_medic_products_stock_nonneg"),
    )
    op.create_index("idx_medic_products_org", "medic_products", ["org_id"])
    op.create_index("idx_medic_products_name", "medic_products", ["org_id", "name"])
    op.execute("""
        CREATE TRIGGER trg_medic_products_updated
        BEFORE UPDATE ON medic_products
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # ── medic_inventory_lots ──────────────────────────────────────────────────
    op.create_table(
        "medic_inventory_lots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True),
                  sa.ForeignKey("medic_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lot_number", sa.String(64)),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("quantity_remaining", sa.Integer, nullable=False),
        sa.Column("expiry_date", sa.Date),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("notes", sa.Text),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.CheckConstraint("quantity > 0", name="ck_medic_lots_qty_pos"),
        sa.CheckConstraint("quantity_remaining >= 0", name="ck_medic_lots_rem_nonneg"),
    )
    op.create_index("idx_medic_lots_product", "medic_inventory_lots", ["product_id"])
    op.create_index("idx_medic_lots_expiry", "medic_inventory_lots",
                    ["product_id", "expiry_date"])

    # ── medic_sales ───────────────────────────────────────────────────────────
    op.create_table(
        "medic_sales",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True),
                  sa.ForeignKey("medic_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("lot_id", UUID(as_uuid=True),
                  sa.ForeignKey("medic_inventory_lots.id", ondelete="SET NULL")),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price_eur", sa.Numeric(10, 2)),
        sa.Column("total_eur", sa.Numeric(10, 2)),
        sa.Column("sale_date", sa.Date, nullable=False,
                  server_default=sa.text("CURRENT_DATE")),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.CheckConstraint("quantity > 0", name="ck_medic_sales_qty_pos"),
    )
    op.create_index("idx_medic_sales_org_date", "medic_sales", ["org_id", "sale_date"])
    op.create_index("idx_medic_sales_product", "medic_sales", ["product_id", "sale_date"])
    op.create_index("idx_medic_sales_agent", "medic_sales", ["agent_id", "sale_date"])

    # ── Seed initial 9 products ───────────────────────────────────────────────
    products = [
        ("Juved",       "Juvederm — filler acido ialuronico",           "siringa"),
        ("Prophilo",    "Profhilo — bio-rimodellante acido ialuronico",  "siringa"),
        ("Vistabex",    "Vistabex — tossina botulinica tipo A",          "flacone"),
        ("Bocout",      "Bocouture — tossina botulinica tipo A",         "flacone"),
        ("Azalou",      "Azalow — skin booster acido ialuronico",        "siringa"),
        ("Flore",       "Flore — skin booster / biostimolante",          "siringa"),
        ("Crema anes",  "Crema anestetica topica",                       "tubo"),
        ("Prx",         "PRX-T33 — peeling chimico",                     "flacone"),
        ("Pqj",         "PQAge Junior — peeling chimico",                "flacone"),
    ]
    for name, description, unit in products:
        op.execute(f"""
            INSERT INTO medic_products (org_id, name, description, unit, stock_qty)
            VALUES (
                '{MEDIC_ORG_ID}',
                '{name}',
                '{description}',
                '{unit}',
                0
            )
            ON CONFLICT ON CONSTRAINT uq_medic_products_org_name DO NOTHING
        """)


def downgrade() -> None:
    op.drop_table("medic_sales")
    op.drop_table("medic_inventory_lots")
    op.drop_table("medic_products")
    op.execute(f"DELETE FROM organizations WHERE id = '{MEDIC_ORG_ID}'")
