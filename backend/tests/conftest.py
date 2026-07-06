"""Test fixtures. NO real database (CI constraint): db.ping and the auth
owner lookup are stubbed; settings come via dependency override."""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chefclaw import auth, db
from chefclaw.app import create_app
from chefclaw.config import Settings, get_settings

TEST_TOKEN = "test-token-for-pytest"
OWNER_ID = uuid.UUID("01890000-0000-7000-8000-000000000001")


@pytest.fixture(autouse=True)
def reset_owner_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the per-process owner-id cache between tests."""
    monkeypatch.setattr(auth, "_cached_owner_id", None)


@pytest.fixture(autouse=True)
def stub_owner_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the seeded-owner query — no database in CI."""

    async def fake_fetch_owner_id() -> uuid.UUID:
        return OWNER_ID

    monkeypatch.setattr(auth, "fetch_owner_id", fake_fetch_owner_id)


@pytest.fixture(autouse=True)
def stub_spend_readout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the health endpoint's ledger reads — the unit tier must never open
    a real connection (the local compose DB is PRODUCTION — kit inversion)."""

    async def fake_spend(owner_id: uuid.UUID) -> None:
        return None

    async def fake_attempts(owner_id: uuid.UUID) -> None:
        return None

    from chefclaw import app as app_module

    monkeypatch.setattr(app_module, "_spend_month_to_date", fake_spend)
    monkeypatch.setattr(app_module, "_attempts_today", fake_attempts)


@pytest.fixture
def ping_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ping() -> bool:
        return True

    monkeypatch.setattr(db, "ping", fake_ping)


@pytest.fixture
def ping_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ping() -> bool:
        return False

    monkeypatch.setattr(db, "ping", fake_ping)


def make_app(token: str = TEST_TOKEN) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(chefclaw_api_token=token)
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Client against an app configured with TEST_TOKEN."""
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def client_no_token() -> AsyncIterator[AsyncClient]:
    """Client against an app with an EMPTY configured token (disabled-closed)."""
    app = make_app(token="")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
