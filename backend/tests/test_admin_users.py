"""Admin per-user budget endpoint (M3) — CI tier (no DB): the users service is
stubbed, the transport/validation/partial-update semantics are exercised for
real. The cap SQL round-trip is the golden tier (test_users_db.py)."""

import uuid
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chefclaw import auth
from chefclaw.app import create_app
from chefclaw.config import Settings, get_settings
from chefclaw.services import users as users_service
from tests.conftest import OWNER_ID

USER_ID = uuid.uuid4()


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _admin_app(**overrides: object) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_auth_provider="fake", chefclaw_fake_owner_id=str(OWNER_ID), **overrides
    )
    return app


def _row(**overrides: object) -> users_service.UserBudgetRow:
    fields: dict[str, object] = dict(
        id=USER_ID, email="friend@x.com", monthly_budget_usd=None, max_attempts_per_day=None
    )
    fields.update(overrides)
    return users_service.UserBudgetRow(**fields)


async def test_set_both_caps_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_set(sm, user_id, *, values):
        captured["user_id"] = user_id
        captured["values"] = values
        return _row(monthly_budget_usd=Decimal("5.00"), max_attempts_per_day=10)

    monkeypatch.setattr(users_service, "set_user_budget", fake_set)
    async with _client(_admin_app()) as client:
        resp = await client.patch(
            f"/api/admin/users/{USER_ID}/budget",
            json={"monthly_budget_usd": 5, "max_attempts_per_day": 10},
        )
    assert resp.status_code == 200
    assert resp.json() == {
        "id": str(USER_ID),
        "email": "friend@x.com",
        "monthly_budget_usd": 5.0,
        "max_attempts_per_day": 10,
    }
    assert captured["user_id"] == USER_ID
    assert captured["values"] == {"monthly_budget_usd": 5.0, "max_attempts_per_day": 10}


async def test_partial_update_only_daily(monkeypatch: pytest.MonkeyPatch) -> None:
    """An omitted field is NOT in the update map — monthly is left untouched."""
    captured: dict[str, object] = {}

    async def fake_set(sm, user_id, *, values):
        captured["values"] = values
        return _row(max_attempts_per_day=3)

    monkeypatch.setattr(users_service, "set_user_budget", fake_set)
    async with _client(_admin_app()) as client:
        resp = await client.patch(
            f"/api/admin/users/{USER_ID}/budget", json={"max_attempts_per_day": 3}
        )
    assert resp.status_code == 200
    assert captured["values"] == {"max_attempts_per_day": 3}


async def test_explicit_null_clears_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit null is a CLEAR (present in the map with None), distinct from
    an absent field — it falls the account back to the global env cap."""
    captured: dict[str, object] = {}

    async def fake_set(sm, user_id, *, values):
        captured["values"] = values
        return _row()  # both None

    monkeypatch.setattr(users_service, "set_user_budget", fake_set)
    async with _client(_admin_app()) as client:
        resp = await client.patch(
            f"/api/admin/users/{USER_ID}/budget", json={"monthly_budget_usd": None}
        )
    assert resp.status_code == 200
    assert captured["values"] == {"monthly_budget_usd": None}
    assert resp.json()["monthly_budget_usd"] is None


async def test_empty_body_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty PATCH sends an empty update map (no-op read-back), not a 422."""
    captured: dict[str, object] = {}

    async def fake_set(sm, user_id, *, values):
        captured["values"] = values
        return _row()

    monkeypatch.setattr(users_service, "set_user_budget", fake_set)
    async with _client(_admin_app()) as client:
        resp = await client.patch(f"/api/admin/users/{USER_ID}/budget", json={})
    assert resp.status_code == 200
    assert captured["values"] == {}


async def test_missing_user_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_set(sm, user_id, *, values):
        return None

    monkeypatch.setattr(users_service, "set_user_budget", fake_set)
    async with _client(_admin_app()) as client:
        resp = await client.patch(
            f"/api/admin/users/{uuid.uuid4()}/budget", json={"max_attempts_per_day": 5}
        )
    assert resp.status_code == 404


async def test_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-admin owner hitting the admin surface directly is a 403 from the
    dependency (critique M9) — the frontend gate is cosmetic only."""

    async def non_admin(owner_id: uuid.UUID) -> auth.Account:
        return auth.Account(id=OWNER_ID, name="friend", email="f@x", is_admin=False)

    monkeypatch.setattr(auth, "fetch_account", non_admin)
    async with _client(_admin_app()) as client:
        resp = await client.patch(
            f"/api/admin/users/{USER_ID}/budget", json={"max_attempts_per_day": 5}
        )
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"monthly_budget_usd": 0},
        {"monthly_budget_usd": -1},
        {"max_attempts_per_day": 0},
        {"max_attempts_per_day": -5},
        {"max_attempts_per_day": 2.5},  # non-integer
        {"unknown_field": 1},  # extra="forbid"
    ],
)
async def test_invalid_body_is_422(monkeypatch: pytest.MonkeyPatch, body: dict) -> None:
    called = {"n": 0}

    async def fake_set(sm, user_id, *, values):
        called["n"] += 1
        return _row()

    monkeypatch.setattr(users_service, "set_user_budget", fake_set)
    async with _client(_admin_app()) as client:
        resp = await client.patch(f"/api/admin/users/{USER_ID}/budget", json=body)
    assert resp.status_code == 422
    assert called["n"] == 0  # validation rejects before the service runs
