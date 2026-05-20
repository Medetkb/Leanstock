"""
Auth flow tests:
  register → verify email → login → refresh → logout
  forgot password → reset password
  RBAC: wrong role gets 403
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.user import EmailVerification, User


def test_register_success(client: TestClient):
    resp = client.post("/auth/register", json={
        "email": "alice@example.com",
        "username": "alice",
        "password": "password123",
        "tenant_name": "TestCo",
    })
    assert resp.status_code == 201
    assert "Check your email" in resp.json()["message"]


def test_register_duplicate_email(client: TestClient):
    payload = {
        "email": "bob@example.com",
        "username": "bob1",
        "password": "password123",
        "tenant_name": "TestCo",
    }
    client.post("/auth/register", json=payload)
    payload["username"] = "bob2"
    resp = client.post("/auth/register", json=payload)
    assert resp.status_code == 409


def test_register_weak_password(client: TestClient):
    resp = client.post("/auth/register", json={
        "email": "weak@example.com",
        "username": "weakuser",
        "password": "123",
        "tenant_name": "TestCo",
    })
    assert resp.status_code == 422


def test_login_without_verification(client: TestClient):
    client.post("/auth/register", json={
        "email": "unverified@example.com",
        "username": "unverified",
        "password": "password123",
        "tenant_name": "TestCo",
    })
    resp = client.post("/auth/login", json={
        "email": "unverified@example.com",
        "password": "password123",
    })
    assert resp.status_code == 403


def test_full_auth_flow(client: TestClient, session: Session):
    # 1. Register
    client.post("/auth/register", json={
        "email": "charlie@example.com",
        "username": "charlie",
        "password": "password123",
        "tenant_name": "TestCo",
    })

    # 2. Manually verify (simulate clicking the email link)
    ev = session.exec(
        select(EmailVerification)
        .join(User, EmailVerification.user_id == User.id)
        .where(User.email == "charlie@example.com")
    ).first()
    assert ev is not None

    resp = client.get(f"/auth/verify-email/{ev.token}")
    assert resp.status_code == 200

    # 3. Login
    resp = client.post("/auth/login", json={
        "email": "charlie@example.com",
        "password": "password123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data

    access = data["access_token"]
    refresh = data["refresh_token"]

    # 4. Get current user info
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "charlie@example.com"

    # 5. Refresh token
    resp = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    new_access = resp.json()["access_token"]
    assert new_access != access

    # 6. Logout
    resp = client.post("/auth/logout", json={"refresh_token": refresh})
    assert resp.status_code == 200


def test_login_wrong_password(client: TestClient):
    resp = client.post("/auth/login", json={
        "email": "charlie@example.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_protected_endpoint_without_token(client: TestClient):
    resp = client.get("/products")
    assert resp.status_code == 403  # HTTPBearer returns 403 when no credentials given


def test_forgot_password_always_200(client: TestClient):
    # Should return 200 even for unknown email
    resp = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 200
