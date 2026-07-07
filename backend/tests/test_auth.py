"""M2 auth surface — CI tier (no DB, no network).

Covers the prod-env guard (M7), require_owner's fake short-circuit + session
path, require_admin (M9), the login→callback cookie flow (M3/M4/M6), logout, and
/api/me. The REAL session insert/resolve/delete and the callback's DB lookup are
exercised by the golden tier (test_auth_db.py)."""

import uuid
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from chefclaw import auth, sessions
from chefclaw.app import create_app
from chefclaw.config import Settings, get_settings
from chefclaw.errors import ConfigError
from chefclaw.oauth import FakeOAuthProvider, VerifiedIdentity
from chefclaw.routers import auth as auth_router
from chefclaw.routers.auth import safe_next
from tests.conftest import OWNER_ID, make_app, make_session_app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── prod-env config guard (critique M7) ──────────────────────────────────────


def test_assert_prod_auth_safe_rejects_unknown_provider() -> None:
    with pytest.raises(ConfigError):
        auth.assert_prod_auth_safe(Settings(chefclaw_auth_provider="bogus"))


def test_assert_prod_auth_safe_rejects_fake_with_real_client_id() -> None:
    with pytest.raises(ConfigError):
        auth.assert_prod_auth_safe(
            Settings(chefclaw_auth_provider="fake", google_oauth_client_id="staged-id")
        )


def test_assert_prod_auth_safe_rejects_fake_in_vps_env() -> None:
    with pytest.raises(ConfigError):
        auth.assert_prod_auth_safe(
            Settings(chefclaw_auth_provider="fake", sentry_environment="vps")
        )


def test_assert_prod_auth_safe_rejects_google_without_creds() -> None:
    """Fail the boot rather than 500 at first login when google is selected but
    the client id/secret is empty (fail-closed, fail-fast)."""
    with pytest.raises(ConfigError):
        auth.assert_prod_auth_safe(Settings(chefclaw_auth_provider="google"))


def test_assert_prod_auth_safe_allows_fake_local_and_google() -> None:
    auth.assert_prod_auth_safe(Settings(chefclaw_auth_provider="fake"))  # default local
    # A fully-configured prod deploy: google auth + ses email, both real.
    auth.assert_prod_auth_safe(
        Settings(
            chefclaw_auth_provider="google",
            google_oauth_client_id="id",
            google_oauth_client_secret="secret",
            chefclaw_email="ses",
            email_from="no-reply@x",
            ses_region="us-east-1",
            sentry_environment="vps",
        )
    )


def test_assert_prod_auth_safe_rejects_fake_email_in_vps_env() -> None:
    """The email footgun is guarded like the auth one (M7): fake email in a
    'vps' env fails the boot (invites would only be logged, never sent)."""
    with pytest.raises(ConfigError):
        auth.assert_prod_auth_safe(
            Settings(
                chefclaw_auth_provider="google",
                google_oauth_client_id="id",
                google_oauth_client_secret="secret",
                sentry_environment="vps",
                # chefclaw_email defaults to "fake"
            )
        )


# ── require_owner (fake short-circuit + guard) ────────────────────────────────


async def test_fake_auth_authenticates_as_fake_owner() -> None:
    async with _client(make_app()) as client:
        resp = await client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(OWNER_ID)


async def test_fake_auth_refuses_when_real_client_id_staged() -> None:
    """require_owner's fake branch refuses to run with a real Google client id
    set (critique M7 guard 2, per-request defense in depth) — the misconfig
    fails CLOSED (the request is refused as a 500), never a silent fake-auth."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_auth_provider="fake", google_oauth_client_id="staged-id"
    )
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/me")
    assert resp.status_code == 500


# ── require_owner (session path) ──────────────────────────────────────────────


async def test_session_auth_401_without_cookie() -> None:
    async with _client(make_session_app()) as client:
        resp = await client.get("/api/me")
    assert resp.status_code == 401


async def test_session_auth_resolves_cookie_via_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """require_owner hashes the cookie and resolves it via fetch_session_owner_id."""
    seen: dict[str, str] = {}

    async def fake_resolve(token_hash: str) -> uuid.UUID:
        seen["hash"] = token_hash
        return OWNER_ID

    monkeypatch.setattr(auth, "fetch_session_owner_id", fake_resolve)
    async with _client(make_session_app()) as client:
        client.cookies.set(auth.SESSION_COOKIE_NAME, "raw-token")
        resp = await client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(OWNER_ID)
    assert seen["hash"] == sessions.hash_token("raw-token")  # hashed, never raw


# ── require_admin (critique M9) ───────────────────────────────────────────────


def _admin_probe_app() -> FastAPI:
    app = make_app()

    @app.get("/api/_probe_admin")
    async def _probe(owner_id: Annotated[uuid.UUID, Depends(auth.require_admin)]) -> dict:
        return {"owner_id": str(owner_id)}

    return app


async def test_require_admin_allows_admin() -> None:
    async with _client(_admin_probe_app()) as client:  # autouse stub = admin
        resp = await client.get("/api/_probe_admin")
    assert resp.status_code == 200


async def test_require_admin_forbids_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    async def non_admin(owner_id: uuid.UUID) -> auth.Account:
        return auth.Account(id=OWNER_ID, name="friend", email="f@x", is_admin=False)

    monkeypatch.setattr(auth, "fetch_account", non_admin)
    async with _client(_admin_probe_app()) as client:
        resp = await client.get("/api/_probe_admin")
    assert resp.status_code == 403


# ── safe next (open-redirect, critique M4) ────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        "https://evil.example",
        "//evil.example",
        "/a\\b",
        "javascript:x",
        "",
        "  /x",
        "/x\r\ny",
        None,
    ],
)
def test_safe_next_rejects_offsite(bad: str | None) -> None:
    assert safe_next(bad) == "/"


@pytest.mark.parametrize("ok", ["/", "/recipes", "/recipes/123?tab=steps"])
def test_safe_next_allows_same_origin(ok: str) -> None:
    assert safe_next(ok) == ok


# ── login → callback cookie flow (M3/M6) ──────────────────────────────────────


async def test_login_redirects_and_sets_tx_cookie() -> None:
    async with _client(make_app()) as client:
        resp = await client.get(
            "/api/auth/google/login", params={"next": "/recipes"}, follow_redirects=False
        )
    assert resp.status_code == 302
    # The fake provider loops back to the callback (drivable without Google).
    assert "/api/auth/google/callback?" in resp.headers["location"]
    assert "state=" in resp.headers["location"]
    set_cookie = "; ".join(resp.headers.get_list("set-cookie"))
    assert "oauth_tx=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "path=/api/auth" in set_cookie.lower()
    assert "max-age=300" in set_cookie.lower()


async def test_callback_missing_tx_cookie_is_400() -> None:
    async with _client(make_app()) as client:
        resp = await client.get(
            "/api/auth/google/callback",
            params={"code": "x", "state": "y"},
            follow_redirects=False,
        )
    assert resp.status_code == 400


async def test_callback_state_mismatch_is_400() -> None:
    async with _client(make_app()) as client:
        login = await client.get("/api/auth/google/login", follow_redirects=False)
        # The oauth_tx cookie is now in the jar; supply a WRONG state param.
        resp = await client.get(
            "/api/auth/google/callback",
            params={"code": "fake-auth-code", "state": "not-the-stashed-state"},
            follow_redirects=False,
        )
    assert login.status_code == 302
    assert resp.status_code == 400


async def _drive_callback(client: AsyncClient):
    """login (stash tx) then GET the fake loop-back callback URL with the jar's
    oauth_tx cookie."""
    login = await client.get("/api/auth/google/login", follow_redirects=False)
    return await client.get(login.headers["location"], follow_redirects=False)


async def test_callback_mints_session_for_returning_user(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(identity: VerifiedIdentity) -> uuid.UUID:
        return OWNER_ID

    async def fake_create(*args: object, **kwargs: object) -> str:
        return "raw-session-token"

    monkeypatch.setattr(auth_router, "resolve_owner_by_identity", resolve)
    monkeypatch.setattr(sessions, "create_session", fake_create)
    async with _client(make_app()) as client:
        resp = await _drive_callback(client)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    set_cookie = "; ".join(resp.headers.get_list("set-cookie"))
    assert f"{auth.SESSION_COOKIE_NAME}=raw-session-token" in set_cookie
    # The single-use tx cookie is cleared on the callback response (M3).
    assert 'oauth_tx=""' in set_cookie or "oauth_tx=;" in set_cookie.lower()


async def test_callback_unbound_identity_is_opaque_403(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(identity: VerifiedIdentity) -> None:
        return None  # not a returning user

    async def no_activation(sm: object, settings: object, identity: VerifiedIdentity) -> None:
        return None  # no bootstrap-claim, no matching invite

    monkeypatch.setattr(auth_router, "resolve_owner_by_identity", resolve)
    monkeypatch.setattr(auth_router.invites, "activate_identity", no_activation)
    async with _client(make_app()) as client:
        resp = await _drive_callback(client)
    assert resp.status_code == 403
    assert resp.json()["error_type"] == "sign_in_denied"


async def test_callback_unverified_email_is_opaque_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """M5: an unverified email is rejected before any account match (opaque)."""
    monkeypatch.setattr(
        FakeOAuthProvider,
        "identity",
        VerifiedIdentity(
            provider="google", subject="s", email="e@x", email_verified=False, name=None
        ),
    )
    async with _client(make_app()) as client:
        resp = await _drive_callback(client)
    assert resp.status_code == 403


# ── logout ────────────────────────────────────────────────────────────────────


async def test_logout_clears_cookie_and_204s() -> None:
    async with _client(make_app()) as client:  # fake auth ⇒ no session to delete
        resp = await client.post("/api/auth/logout")
    assert resp.status_code == 204
    set_cookie = "; ".join(resp.headers.get_list("set-cookie"))
    assert auth.SESSION_COOKIE_NAME in set_cookie  # a clearing Set-Cookie
