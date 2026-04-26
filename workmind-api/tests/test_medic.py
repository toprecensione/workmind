"""
Tests for MEDIC domain endpoints.
Covers: products CRUD, inventory lots, sales, stock corrections, warehouse.
Field names match bender's actual API schema (price_eur, unit_price_eur, low_stock_threshold).
"""
from __future__ import annotations

import uuid
import pytest
import pytest_asyncio
from sqlalchemy import text


# ── Helpers ───────────────────────────────────────────────────────────────────

MEDIC_ORG_ID = "00000000-0000-0000-0000-000000000002"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def clean_medic_tables(test_session_factory):
    """Truncate MEDIC tables before test session to avoid 409 conflicts from previous runs."""
    async with test_session_factory() as session:
        # Order matters: child tables first
        for table in ("medic_sales", "medic_stock_corrections", "medic_inventory_lots", "medic_products"):
            try:
                await session.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
            except Exception:
                await session.rollback()
        await session.commit()


async def _create_product(client, auth_headers, name="Test Prodotto", stock=0):
    """Create a MEDIC product. If stock > 0, add via an inventory lot."""
    resp = await client.post(
        "/api/medic/products",
        json={
            "name": name,
            "price_eur": 25.0,
            "low_stock_threshold": 2,
        },
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), resp.text
    product = resp.json()

    if stock > 0:
        lot_resp = await client.post(
            f"/api/medic/products/{product['id']}/lots",
            json={"quantity": stock},
            headers=auth_headers,
        )
        assert lot_resp.status_code in (200, 201), lot_resp.text
        # Refresh to get updated stock_qty
        refresh = await client.get(f"/api/medic/products/{product['id']}", headers=auth_headers)
        assert refresh.status_code == 200
        return refresh.json()

    return product


# ── Products ──────────────────────────────────────────────────────────────────

class TestProducts:
    @pytest.mark.asyncio
    async def test_list_products_empty(self, client, auth_headers):
        resp = await client.get("/api/medic/products", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_product(self, client, auth_headers):
        resp = await client.post(
            "/api/medic/products",
            json={
                "name": "Juvéderm Ultra 1ml",
                "price_eur": 85.0,
                "low_stock_threshold": 3,
            },
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()
        assert data["name"] == "Juvéderm Ultra 1ml"
        assert data["stock_qty"] == 0          # stock starts at 0; add via lots
        assert data["price_eur"] == 85.0
        assert "id" in data

    @pytest.mark.asyncio
    async def test_get_product_by_id(self, client, auth_headers):
        product = await _create_product(client, auth_headers, name="Botox 100U")
        product_id = product["id"]

        resp = await client.get(f"/api/medic/products/{product_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == product_id
        assert data["name"] == "Botox 100U"

    @pytest.mark.asyncio
    async def test_get_product_not_found(self, client, auth_headers):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/medic/products/{fake_id}", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_product(self, client, auth_headers):
        product = await _create_product(client, auth_headers, name="Radiesse 1.5ml")
        product_id = product["id"]

        resp = await client.put(
            f"/api/medic/products/{product_id}",
            json={"name": "Radiesse 1.5ml — Updated", "price_eur": 95.0},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["price_eur"] == 95.0

    @pytest.mark.asyncio
    async def test_delete_product(self, client, auth_headers):
        product = await _create_product(client, auth_headers, name="Delete Me")
        product_id = product["id"]

        resp = await client.delete(f"/api/medic/products/{product_id}", headers=auth_headers)
        assert resp.status_code in (200, 204), resp.text

        # Soft-delete: product still exists but is_active=False (or 404 on hard-delete)
        resp2 = await client.get(f"/api/medic/products/{product_id}", headers=auth_headers)
        if resp2.status_code == 200:
            assert resp2.json().get("is_active") is False
        else:
            assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_create_product_missing_name(self, client, auth_headers):
        resp = await client.post(
            "/api/medic/products",
            json={"price_eur": 25.0},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_products_require_auth(self, client):
        resp = await client.get("/api/medic/products")
        assert resp.status_code == 401


# ── Inventory Lots ────────────────────────────────────────────────────────────

class TestInventoryLots:
    @pytest.mark.asyncio
    async def test_create_lot_increases_stock(self, client, auth_headers):
        product = await _create_product(client, auth_headers, name="Lot Test Prodotto", stock=0)
        product_id = product["id"]

        resp = await client.post(
            f"/api/medic/products/{product_id}/lots",
            json={
                "lot_number": "LOT-2026-001",
                "quantity": 15,
                "expiry_date": "2027-12-31",
            },
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201), resp.text

        # Verify stock increased
        prod_resp = await client.get(f"/api/medic/products/{product_id}", headers=auth_headers)
        assert prod_resp.status_code == 200
        assert prod_resp.json()["stock_qty"] == 15

    @pytest.mark.asyncio
    async def test_list_lots_for_product(self, client, auth_headers):
        product = await _create_product(client, auth_headers, name="Lot List Prodotto", stock=0)
        product_id = product["id"]

        # Create 2 lots
        for i in range(2):
            await client.post(
                f"/api/medic/products/{product_id}/lots",
                json={"lot_number": f"LOT-{i}", "quantity": 5},
                headers=auth_headers,
            )

        resp = await client.get(f"/api/medic/products/{product_id}/lots", headers=auth_headers)
        assert resp.status_code == 200
        lots = resp.json()
        assert len(lots) >= 2


# ── Sales ─────────────────────────────────────────────────────────────────────

class TestSales:
    @pytest.mark.asyncio
    async def test_create_sale(self, client, auth_headers):
        product = await _create_product(client, auth_headers, name="Sale Test Prodotto", stock=20)
        product_id = product["id"]

        resp = await client.post(
            "/api/medic/sales",
            json={
                "product_id": product_id,
                "quantity": 2,
                "unit_price_eur": 85.0,
                "sale_date": "2026-04-25",
                "notes": "Test sale",
            },
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()
        assert data["quantity"] == 2
        assert "id" in data

    @pytest.mark.asyncio
    async def test_sale_reduces_stock(self, client, auth_headers):
        product = await _create_product(
            client, auth_headers, name="Stock Check Prodotto", stock=10
        )
        product_id = product["id"]

        await client.post(
            "/api/medic/sales",
            json={"product_id": product_id, "quantity": 3, "unit_price_eur": 50.0},
            headers=auth_headers,
        )

        prod_resp = await client.get(f"/api/medic/products/{product_id}", headers=auth_headers)
        assert prod_resp.status_code == 200
        assert prod_resp.json()["stock_qty"] == 7  # 10 - 3

    @pytest.mark.asyncio
    async def test_list_sales(self, client, auth_headers):
        resp = await client.get("/api/medic/sales", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_sale_insufficient_stock(self, client, auth_headers):
        # Product has 0 stock (no lots added)
        product = await _create_product(client, auth_headers, name="Low Stock Prodotto", stock=0)
        product_id = product["id"]

        resp = await client.post(
            "/api/medic/sales",
            json={"product_id": product_id, "quantity": 50, "unit_price_eur": 50.0},
            headers=auth_headers,
        )
        # Should fail — not enough stock (400, 409, or 422)
        assert resp.status_code in (400, 409, 422), resp.text

    @pytest.mark.asyncio
    async def test_void_sale_restores_stock(self, client, auth_headers):
        product = await _create_product(client, auth_headers, name="Void Sale Prodotto", stock=10)
        product_id = product["id"]

        sale_resp = await client.post(
            "/api/medic/sales",
            json={"product_id": product_id, "quantity": 2, "unit_price_eur": 50.0},
            headers=auth_headers,
        )
        assert sale_resp.status_code in (200, 201), sale_resp.text
        sale_id = sale_resp.json()["id"]

        # Void the sale
        void_resp = await client.delete(f"/api/medic/sales/{sale_id}", headers=auth_headers)
        assert void_resp.status_code in (200, 204), void_resp.text

        # Stock should be restored
        prod_resp = await client.get(f"/api/medic/products/{product_id}", headers=auth_headers)
        assert prod_resp.json()["stock_qty"] == 10


# ── Statistics ────────────────────────────────────────────────────────────────

class TestStats:
    @pytest.mark.asyncio
    async def test_stats_summary_structure(self, client, auth_headers):
        resp = await client.get("/api/medic/stats/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Response: { "period": {...}, "totals": {"sales_count", "units_sold", "revenue_eur"}, ... }
        assert "totals" in data, f"Missing 'totals' key. Got: {list(data.keys())}"
        assert "sales_count" in data["totals"]
        assert "revenue_eur" in data["totals"]

    @pytest.mark.asyncio
    async def test_stats_by_product(self, client, auth_headers):
        resp = await client.get("/api/medic/stats/by-product", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_stats_by_agent(self, client, auth_headers):
        resp = await client.get("/api/medic/stats/by-agent", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_stats_date_filter(self, client, auth_headers):
        resp = await client.get(
            "/api/medic/stats/summary?date_from=2026-01-01&date_to=2026-12-31",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_stats_require_auth(self, client):
        resp = await client.get("/api/medic/stats/summary")
        assert resp.status_code == 401


# ── Inventory endpoint ────────────────────────────────────────────────────────

class TestInventory:
    @pytest.mark.asyncio
    async def test_list_inventory(self, client, auth_headers):
        resp = await client.get("/api/medic/inventory", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_stock_correction(self, client, auth_headers):
        product = await _create_product(client, auth_headers, name="Correction Prodotto", stock=10)
        product_id = product["id"]

        resp = await client.post(
            f"/api/medic/products/{product_id}/stock-correction",
            json={
                "delta": -3,
                "reason": "Prodotto scaduto",
            },
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201), resp.text
        prod_resp = await client.get(f"/api/medic/products/{product_id}", headers=auth_headers)
        assert prod_resp.json()["stock_qty"] == 7
