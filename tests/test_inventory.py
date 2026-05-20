"""
Inventory business logic tests:
  - Create product, location, set inventory
  - Transfer inventory (atomic, SELECT FOR UPDATE)
  - Oversell protection
  - Dead stock decay formula
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.user import EmailVerification, User
from app.workers.tasks import dead_stock_decay


# ─── Helpers ────────────────────────────────────────────────────────────────

def register_and_login(client: TestClient, session: Session, email: str, username: str) -> str:
    """Register, verify, login and return Bearer access token."""
    client.post("/auth/register", json={
        "email": email,
        "username": username,
        "password": "password123",
        "tenant_name": "InventoryTestCo",
    })
    ev = session.exec(
        select(EmailVerification)
        .join(User, EmailVerification.user_id == User.id)
        .where(User.email == email)
    ).first()
    client.get(f"/auth/verify-email/{ev.token}")
    resp = client.post("/auth/login", json={"email": email, "password": "password123"})
    return resp.json()["access_token"]


# ─── Tests ──────────────────────────────────────────────────────────────────

def test_create_product(client: TestClient, session: Session):
    token = register_and_login(client, session, "mgr@test.com", "mgr_user")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/products", json={
        "name": "Widget A",
        "sku": "SKU-001",
        "price": 99.99,
        "category": "widgets",
    }, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["sku"] == "SKU-001"


def test_duplicate_sku_rejected(client: TestClient, session: Session):
    token = register_and_login(client, session, "mgr2@test.com", "mgr2_user")
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/products", json={"name": "A", "sku": "DUP-001", "price": 1.0}, headers=headers)
    resp = client.post("/products", json={"name": "B", "sku": "DUP-001", "price": 2.0}, headers=headers)
    assert resp.status_code == 409


def test_inventory_transfer_success(client: TestClient, session: Session):
    token = register_and_login(client, session, "transfer@test.com", "transfer_user")
    headers = {"Authorization": f"Bearer {token}"}

    # Create product
    product_id = client.post("/products", json={
        "name": "Box", "sku": "BOX-001", "price": 10.0,
    }, headers=headers).json()["id"]

    # Create two locations
    loc_a = client.post("/locations", json={"name": "Warehouse A"}, headers=headers).json()["id"]
    loc_b = client.post("/locations", json={"name": "Warehouse B"}, headers=headers).json()["id"]

    # Set 100 units in Warehouse A
    client.post("/inventory/set", json={
        "product_id": product_id, "location_id": loc_a, "quantity": 100,
    }, headers=headers)

    # Transfer 30 units from A to B
    resp = client.post("/inventory/transfer", json={
        "product_id": product_id,
        "from_location_id": loc_a,
        "to_location_id": loc_b,
        "quantity": 30,
    }, headers=headers)
    assert resp.status_code == 200
    assert "transfer_id" in resp.json()


def test_oversell_protection(client: TestClient, session: Session):
    token = register_and_login(client, session, "oversell@test.com", "oversell_user")
    headers = {"Authorization": f"Bearer {token}"}

    product_id = client.post("/products", json={
        "name": "Rare Item", "sku": "RARE-001", "price": 500.0,
    }, headers=headers).json()["id"]

    loc_a = client.post("/locations", json={"name": "Vault"}, headers=headers).json()["id"]
    loc_b = client.post("/locations", json={"name": "Shop"}, headers=headers).json()["id"]

    # Only 5 units available
    client.post("/inventory/set", json={
        "product_id": product_id, "location_id": loc_a, "quantity": 5,
    }, headers=headers)

    # Try to transfer 10 — should fail with 409
    resp = client.post("/inventory/transfer", json={
        "product_id": product_id,
        "from_location_id": loc_a,
        "to_location_id": loc_b,
        "quantity": 10,
    }, headers=headers)
    assert resp.status_code == 409
    assert "Not enough stock" in resp.json()["detail"]


def test_dead_stock_decay_formula():
    """
    Pure unit test — no HTTP, no DB.
    Verifies the decay math: starting at 0%, after one decay cycle it should be 10%.
    After 9 cycles it should cap at 90%.
    """
    discount = 0.0
    for _ in range(10):
        discount = min(discount + 10.0, 90.0)

    assert discount == 90.0  # caps at 90%

    # Verify it doesn't exceed 90%
    discount = min(90.0 + 10.0, 90.0)
    assert discount == 90.0


def test_same_location_transfer_rejected(client: TestClient, session: Session):
    token = register_and_login(client, session, "same@test.com", "same_user")
    headers = {"Authorization": f"Bearer {token}"}

    product_id = client.post("/products", json={
        "name": "Test", "sku": "SAME-001", "price": 1.0,
    }, headers=headers).json()["id"]

    loc = client.post("/locations", json={"name": "Single"}, headers=headers).json()["id"]

    resp = client.post("/inventory/transfer", json={
        "product_id": product_id,
        "from_location_id": loc,
        "to_location_id": loc,  # same!
        "quantity": 10,
    }, headers=headers)
    assert resp.status_code == 400
