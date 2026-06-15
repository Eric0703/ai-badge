"""Test configuration — Phase 1A backend tests (function-scoped engine).

Architecture:
  _test_engine     function-scoped: create/drop tables per test
  db               autouse: own AsyncSession from pool
  _override_get_db autouse: each HTTP request gets its own AsyncSession
  async_client     ASGI HTTP client

Key design: HTTP sessions and db fixture are COMPLETELY independent.
No shared sessions, no shared connections.  TRUNCATE between tests.

Test helpers:
  create_test_user_with_org_and_device(db)
  create_test_session(db, user_id, device_id, ...)
"""

import os
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ai_badge:ai_badge_dev@localhost:5432/ai_badge_test",
)

TRUNCATE_ORDER = [
    "workflow_events", "deletion_jobs", "audit_logs",
    "jobs", "artifacts", "sessions",
    "devices", "users", "organizations",
]


# ── Function-scoped engine ───────────────────────────────────────────

@pytest_asyncio.fixture
async def _test_engine():
    """Function-scoped engine — fresh tables for every test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # TRUNCATE to be extra safe, then close
    async with engine.connect() as conn:
        tables = ", ".join(TRUNCATE_ORDER)
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        await conn.commit()

    await engine.dispose()


# ── db fixture: own session ──────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def db(
    _test_engine,
    monkeypatch,
    tmp_path: Path,
) -> AsyncGenerator[AsyncSession, None]:
    """Per-test DB session — independent from HTTP sessions."""
    from app.config import settings as app_settings

    storage_dir = tmp_path / "audio"
    storage_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(app_settings, "audio_storage_path", str(storage_dir))

    async with _test_engine.connect() as conn:
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await session.commit()
        await session.close()


# ── get_db override: each HTTP request gets its own session ──────────

@pytest_asyncio.fixture(autouse=True)
async def _override_get_db(_test_engine):
    """Each HTTP request creates a fresh AsyncSession from the pool."""

    async def _test_get_db():
        async with _test_engine.connect() as conn:
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _test_get_db
    yield
    app.dependency_overrides.clear()


# ── HTTP client ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── Auth fixtures ────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def auth_headers(async_client: AsyncClient) -> dict:
    resp = await async_client.post("/api/v1/auth/register", json={
        "email": f"test-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test-password-123",
        "display_name": "Test User",
        "org_name": f"Test Org {uuid.uuid4().hex[:6]}",
    })
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def auth_headers2(async_client: AsyncClient) -> dict:
    resp = await async_client.post("/api/v1/auth/register", json={
        "email": f"test2-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test-password-456",
        "display_name": "Test User 2",
        "org_name": f"Test Org 2 {uuid.uuid4().hex[:6]}",
    })
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def session_id(async_client: AsyncClient, auth_headers: dict) -> str:
    resp = await async_client.post("/api/v1/sessions", json={
        "title": "Test Session",
    }, headers=auth_headers)
    assert resp.status_code == 201, f"Create session failed: {resp.text}"
    sid = resp.json()["id"]
    resp = await async_client.patch(
        f"/api/v1/sessions/{sid}/consent",
        json={"consent": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Consent failed: {resp.text}"
    return sid


# ── Mock provider injection ──────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
def mock_whisper_provider():
    from app.capture.service import set_transcriber
    from app.providers.mock_whisper import MockWhisperProvider
    set_transcriber(MockWhisperProvider())
    yield
    set_transcriber(None)


@pytest_asyncio.fixture(autouse=True)
def mock_llm_provider():
    from app.agents.distiller import set_llm
    from tests.mock_providers import DeterministicMockLLM
    set_llm(DeterministicMockLLM())
    yield
    set_llm(None)


# ── Test helpers ─────────────────────────────────────────────────────

async def create_test_user_with_org_and_device(
    db: AsyncSession,
    email: Optional[str] = None,
    display_name: str = "Test User",
) -> tuple:
    from app.models.organization import Organization
    from app.models.user import User
    from app.models.device import Device

    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Test Org {suffix}", slug=f"test-org-{suffix}")
    db.add(org)
    await db.flush()

    user = User(
        org_id=org.id,
        email=email or f"test-{suffix}@example.com",
        password_hash="hashed",
        display_name=display_name,
        role="owner",
    )
    db.add(user)
    await db.flush()

    device = Device(
        user_id=user.id,
        name="virtual_phone_mic",
        device_type="virtual_phone_mic",
        device_key=f"virtual-{user.id}",
        status="active",
    )
    db.add(device)
    await db.flush()

    return user, org, device


async def create_test_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    device_id: uuid.UUID,
    status: str = "idle",
    consent_granted: bool = True,
    audio_key: Optional[str] = None,
    title: str = "Test Session",
) -> "SessionModel":
    from app.models.session import Session as SessionModel

    session = SessionModel(
        user_id=user_id,
        device_id=device_id,
        status=status,
        consent_granted=consent_granted,
        audio_key=audio_key,
        title=title,
    )
    db.add(session)
    await db.flush()
    return session
