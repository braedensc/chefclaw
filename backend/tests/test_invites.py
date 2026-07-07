"""Invite routes — CI tier (no DB): the invites service is stubbed, the fake
console email adapter runs for real. The real invite SQL (issue/consume/
bootstrap/revoke/public-shape) is the golden tier (test_invites_db.py)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chefclaw import auth
from chefclaw.app import create_app
from chefclaw.config import Settings, get_settings
from chefclaw.services import invites as invites_service
from tests.conftest import OWNER_ID

_NOW = datetime(2026, 7, 7, tzinfo=UTC)


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _admin_app(**settings_overrides: object) -> FastAPI:
    kwargs: dict[str, object] = dict(
        chefclaw_auth_provider="fake",
        chefclaw_fake_owner_id=str(OWNER_ID),
        public_base_url="http://localhost:8000",
        chefclaw_email="fake",
    )
    kwargs.update(settings_overrides)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(**kwargs)
    return app


def _row(**overrides: object) -> invites_service.InviteRow:
    fields = dict(
        id=uuid.uuid4(),
        email="friend@x.com",
        status="pending",
        expires_at=_NOW + timedelta(days=7),
        created_at=_NOW,
        accepted_at=None,
    )
    fields.update(overrides)
    return invites_service.InviteRow(**fields)


# ── POST /api/admin/invites ───────────────────────────────────────────────────


async def test_create_invite_new_returns_201_with_dev_link(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_member(sm: object, email: str) -> bool:
        return False

    async def issue(sm, settings, *, invited_by, email):
        return _row(email=email), "raw-tok", True

    monkeypatch.setattr(invites_service, "active_member_exists", no_member)
    monkeypatch.setattr(invites_service, "issue_invite", issue)
    async with _client(_admin_app()) as client:
        resp = await client.post("/api/admin/invites", json={"email": "Friend@X.com"})
    assert resp.status_code == 201
    body = resp.json()
    # The dev link is surfaced only under fake email; token_hash never leaves.
    assert body["dev_activation_link"] == "http://localhost:8000/invite/raw-tok"
    assert "token_hash" not in body


async def test_create_invite_reissue_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_member(sm: object, email: str) -> bool:
        return False

    async def issue(sm, settings, *, invited_by, email):
        return _row(email=email), "raw-tok", False  # is_new=False → rotate/resend

    monkeypatch.setattr(invites_service, "active_member_exists", no_member)
    monkeypatch.setattr(invites_service, "issue_invite", issue)
    async with _client(_admin_app()) as client:
        resp = await client.post("/api/admin/invites", json={"email": "friend@x.com"})
    assert resp.status_code == 200


async def test_create_invite_active_member_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    async def yes_member(sm: object, email: str) -> bool:
        return True

    monkeypatch.setattr(invites_service, "active_member_exists", yes_member)
    async with _client(_admin_app()) as client:
        resp = await client.post("/api/admin/invites", json={"email": "member@x.com"})
    assert resp.status_code == 409


async def test_create_invite_without_public_base_url_is_503() -> None:
    async with _client(_admin_app(public_base_url="")) as client:
        resp = await client.post("/api/admin/invites", json={"email": "friend@x.com"})
    assert resp.status_code == 503


async def test_create_invite_rejects_malformed_email() -> None:
    async with _client(_admin_app()) as client:
        resp = await client.post("/api/admin/invites", json={"email": "not-an-email"})
    assert resp.status_code == 422


async def test_admin_routes_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-admin owner hitting the admin surface directly is a 403 from the
    dependency (critique M9) — the frontend gate is cosmetic only."""

    async def non_admin(owner_id: uuid.UUID) -> auth.Account:
        return auth.Account(id=OWNER_ID, name="friend", email="f@x", is_admin=False)

    monkeypatch.setattr(auth, "fetch_account", non_admin)
    async with _client(_admin_app()) as client:
        create = await client.post("/api/admin/invites", json={"email": "friend@x.com"})
        listing = await client.get("/api/admin/invites")
        revoke = await client.post(f"/api/admin/invites/{uuid.uuid4()}/revoke")
    assert create.status_code == 403
    assert listing.status_code == 403
    assert revoke.status_code == 403


# ── GET /api/admin/invites + revoke ───────────────────────────────────────────


async def test_list_invites_omits_token_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    async def listing(sm, *, status=None):
        return [_row(email="a@x.com"), _row(email="b@x.com", status="accepted")]

    monkeypatch.setattr(invites_service, "list_invites", listing)
    async with _client(_admin_app()) as client:
        resp = await client.get("/api/admin/invites")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert all("token_hash" not in item for item in items)


@pytest.mark.parametrize(
    "outcome,expected",
    [("revoked", 200), ("already_accepted", 409), ("not_found", 404)],
)
async def test_revoke_outcomes(
    monkeypatch: pytest.MonkeyPatch, outcome: str, expected: int
) -> None:
    async def revoke(sm, invite_id):
        return outcome

    monkeypatch.setattr(invites_service, "revoke_invite", revoke)
    async with _client(_admin_app()) as client:
        resp = await client.post(f"/api/admin/invites/{uuid.uuid4()}/revoke")
    assert resp.status_code == expected


# ── GET /api/invites/{token} (public, M13) ────────────────────────────────────


async def test_public_invite_pending_reveals_email(monkeypatch: pytest.MonkeyPatch) -> None:
    async def public(sm, token):
        return invites_service.PublicInvite(status="pending", email="friend@x.com")

    monkeypatch.setattr(invites_service, "public_invite", public)
    async with _client(_admin_app()) as client:
        resp = await client.get("/api/invites/some-token")
    assert resp.status_code == 200
    assert resp.json() == {"status": "pending", "email": "friend@x.com"}


async def test_public_invite_invalid_is_uniform_no_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """M13: a missing/expired/revoked token is a uniform 'invalid' with no email
    (no enumeration oracle, no address leak)."""

    async def public(sm, token):
        return invites_service.PublicInvite(status="invalid", email=None)

    monkeypatch.setattr(invites_service, "public_invite", public)
    async with _client(_admin_app()) as client:
        resp = await client.get("/api/invites/whatever")
    assert resp.status_code == 200
    assert resp.json() == {"status": "invalid", "email": None}
