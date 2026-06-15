"""Unit tests — Auth module: bcrypt, JWT, register, login.

Tests:
- Password hashing and verification
- JWT creation, decoding, expiry, tampering
- Register endpoint (happy path, duplicate email, validation)
- Login endpoint (happy path, wrong password, non-existent user)
"""

import uuid
import time

import pytest
from httpx import AsyncClient
from jose import JWTError, jwt

from app.auth.service import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)
from app.config import settings


# ══════════════════════════════════════════════════════════════════════
# bcrypt tests
# ══════════════════════════════════════════════════════════════════════

class TestBcrypt:
    """Password hashing and verification."""

    def test_hash_password_returns_string(self):
        hashed = hash_password("my-secret-password")
        assert isinstance(hashed, str)
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    def test_hash_password_is_deterministic_for_verification(self):
        hashed = hash_password("test12345")
        assert verify_password("test12345", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_password_different_each_time(self):
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert h1 != h2  # bcrypt salts are random
        assert verify_password("same-password", h1)
        assert verify_password("same-password", h2)


# ══════════════════════════════════════════════════════════════════════
# JWT tests
# ══════════════════════════════════════════════════════════════════════

class TestJWT:
    """JWT creation, decoding, expiry, tampering."""

    @pytest.fixture
    def user_ids(self):
        return uuid.uuid4(), uuid.uuid4()

    def test_create_access_token(self, user_ids):
        uid, oid = user_ids
        token = create_access_token(uid, oid, "owner")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_decode_access_token(self, user_ids):
        uid, oid = user_ids
        token = create_access_token(uid, oid, "owner")
        payload = decode_access_token(token)
        assert payload["sub"] == str(uid)
        assert payload["org_id"] == str(oid)
        assert payload["role"] == "owner"

    def test_token_with_invalid_signature(self, user_ids):
        uid, oid = user_ids
        # Sign with a different secret
        payload = {"sub": str(uid), "org_id": str(oid), "role": "owner"}
        forged = jwt.encode(payload, "wrong-secret-key", algorithm="HS256")
        with pytest.raises(JWTError):
            decode_access_token(forged)

    def test_token_with_wrong_algorithm(self, user_ids):
        uid, oid = user_ids
        payload = {"sub": str(uid), "org_id": str(oid), "role": "owner"}
        forged = jwt.encode(payload, settings.secret_key, algorithm="HS384")
        with pytest.raises(JWTError):
            decode_access_token(forged)

    def test_expired_token(self, user_ids):
        uid, oid = user_ids
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(uid),
            "org_id": str(oid),
            "role": "owner",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),  # Already expired
        }
        expired_token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
        with pytest.raises(JWTError):
            decode_access_token(expired_token)

    def test_tampered_payload(self, user_ids):
        uid, oid = user_ids
        token = create_access_token(uid, oid, "owner")
        # Tamper with the token (add a character)
        tampered = token + "x"
        with pytest.raises(JWTError):
            decode_access_token(tampered)


# ══════════════════════════════════════════════════════════════════════
# Register endpoint tests
# ══════════════════════════════════════════════════════════════════════

class TestRegister:
    """POST /api/v1/auth/register"""

    @pytest.mark.asyncio
    async def test_register_creates_user_and_returns_token(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/auth/register", json={
            "email": "alice@example.com",
            "password": "secure-password-123",
            "display_name": "Alice",
            "org_name": "Alice Corp",
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "owner"
        assert data["user_id"]
        assert data["org_id"]

    @pytest.mark.asyncio
    async def test_register_duplicate_email_fails(self, async_client: AsyncClient):
        payload = {
            "email": "bob@example.com",
            "password": "secure-password-456",
            "display_name": "Bob",
            "org_name": "Bob Corp",
        }
        # First registration
        resp1 = await async_client.post("/api/v1/auth/register", json=payload)
        assert resp1.status_code == 201

        # Second registration with same email
        resp2 = await async_client.post("/api/v1/auth/register", json=payload)
        assert resp2.status_code == 409, resp2.text
        assert "already registered" in resp2.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "password": "secure-password-123",
            "display_name": "Test",
            "org_name": "Test Org",
        })
        assert resp.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_register_short_password(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            "password": "short",  # < 8 chars
            "display_name": "Test",
            "org_name": "Test Org",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_empty_display_name(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            "password": "secure-password-123",
            "display_name": "",  # empty
            "org_name": "Test Org",
        })
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Login endpoint tests
# ══════════════════════════════════════════════════════════════════════

class TestLogin:
    """POST /api/v1/auth/login"""

    @pytest.mark.asyncio
    async def test_login_success(self, async_client: AsyncClient):
        # Register first
        await async_client.post("/api/v1/auth/register", json={
            "email": "login-test@example.com",
            "password": "mypassword123",
            "display_name": "Login Tester",
            "org_name": "Login Org",
        })

        # Then login
        resp = await async_client.post("/api/v1/auth/login", json={
            "email": "login-test@example.com",
            "password": "mypassword123",
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, async_client: AsyncClient):
        # Register first
        await async_client.post("/api/v1/auth/register", json={
            "email": "wrong-pw@example.com",
            "password": "correct-password",
            "display_name": "PW Tester",
            "org_name": "PW Org",
        })

        # Login with wrong password
        resp = await async_client.post("/api/v1/auth/login", json={
            "email": "wrong-pw@example.com",
            "password": "wrong-password",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/auth/login", json={
            "email": "nobody@example.com",
            "password": "whatever123",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticated_request_with_token(self, async_client: AsyncClient):
        """Use the token from login to access a protected endpoint."""
        # Register
        await async_client.post("/api/v1/auth/register", json={
            "email": "auth-test@example.com",
            "password": "authpass123",
            "display_name": "Auth Tester",
            "org_name": "Auth Org",
        })

        # Login
        login_resp = await async_client.post("/api/v1/auth/login", json={
            "email": "auth-test@example.com",
            "password": "authpass123",
        })
        token = login_resp.json()["access_token"]

        # Access protected endpoint
        resp = await async_client.get(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200  # Should be allowed

    @pytest.mark.asyncio
    async def test_authenticated_request_without_token(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/sessions")
        assert resp.status_code == 401  # Unauthorized

    @pytest.mark.asyncio
    async def test_authenticated_request_with_invalid_token(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/api/v1/sessions",
            headers={"Authorization": "Bearer this-is-not-a-valid-jwt-token"},
        )
        assert resp.status_code == 401
