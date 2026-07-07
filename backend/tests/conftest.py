"""Test fixtures. NO real database (CI constraint).

M2 auth: the unit tier runs in FAKE auth mode — ``require_owner`` short-circuits
to ``OWNER_ID`` (no cookie/session/DB read). ``make_session_app`` builds a
GOOGLE-mode app (the real cookie→session path) for the 401/session tests, which
stub ``auth.fetch_session_owner_id``. The identity read (/api/me, require_admin)
is stubbed via ``auth.fetch_account``.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chefclaw import auth, db
from chefclaw.app import create_app
from chefclaw.config import Settings, get_settings

# Legacy bearer value — kept only so the many existing tests can keep sending a
# header; fake auth IGNORES it (auth is a cookie session now).
TEST_TOKEN = "test-token-for-pytest"
OWNER_ID = uuid.UUID("01890000-0000-7000-8000-000000000001")


@pytest.fixture(autouse=True)
def stub_account_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the /api/me + require_admin identity read (no DB in CI). Default is
    the admin owner; a test wanting a non-admin re-stubs ``auth.fetch_account``."""

    async def fake_fetch_account(owner_id: uuid.UUID) -> auth.Account:
        return auth.Account(id=OWNER_ID, name="owner", email="owner@localhost", is_admin=True)

    monkeypatch.setattr(auth, "fetch_account", fake_fetch_account)


@pytest.fixture(autouse=True)
def stub_spend_readout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the health endpoint's ledger reads — the unit tier must never open
    a real connection (the local compose DB is PRODUCTION — kit inversion)."""

    async def fake_spend(owner_id: uuid.UUID) -> None:
        return None

    async def fake_attempts(owner_id: uuid.UUID) -> None:
        return None

    async def fake_user_caps(owner_id: uuid.UUID) -> tuple[None, None]:
        return None, None

    async def fake_paid_tier(owner_id: uuid.UUID) -> bool:
        return False

    from chefclaw import app as app_module

    monkeypatch.setattr(app_module, "_spend_month_to_date", fake_spend)
    monkeypatch.setattr(app_module, "_attempts_today", fake_attempts)
    # M3: the health endpoint's per-user reads must never open the real
    # (production) DB in the unit tier — default to 'no per-user override' /
    # 'free tier'.
    monkeypatch.setattr(app_module, "_user_budget_caps", fake_user_caps)
    monkeypatch.setattr(app_module, "_owner_paid_tier", fake_paid_tier)


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


def make_app() -> FastAPI:
    """App in FAKE auth mode: require_owner short-circuits to OWNER_ID (no
    cookie/session/DB read), so authed routes work without a database."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_auth_provider="fake", chefclaw_fake_owner_id=str(OWNER_ID)
    )
    return app


def make_session_app(**settings_overrides: object) -> FastAPI:
    """App in GOOGLE (session) auth mode: require_owner reads the chefclaw_session
    cookie and resolves it via ``auth.fetch_session_owner_id`` (stub it)."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_auth_provider="google", **settings_overrides
    )
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Client against a FAKE-auth app (authenticated as OWNER_ID)."""
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def unauth_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """Session-mode client with NO valid session (fetch_session_owner_id → None)
    — every authed route 401s. The replacement for the old disabled-closed
    bearer client."""

    async def no_session(token_hash: str) -> None:
        return None

    monkeypatch.setattr(auth, "fetch_session_owner_id", no_session)
    app = make_session_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


def bearer(token: str) -> dict[str, str]:
    """Legacy helper — fake auth ignores the header, but keeping it avoids
    churning ~60 call sites that still pass it."""
    return {"Authorization": f"Bearer {token}"}
