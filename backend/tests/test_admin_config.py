"""Admin config panel API (GET/PATCH /api/admin/config, ADR admin-config-panel)
— CI tier (no DB): the config service's DB reads/writes are stubbed, the
transport/auth/validation/response-shaping are exercised for real. The persist +
config_audit round-trip and per-job pickup are the golden tier."""

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chefclaw import auth
from chefclaw.app import create_app
from chefclaw.config import Settings, get_settings
from chefclaw.services import config as config_service
from tests.conftest import OWNER_ID


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _admin_app(**overrides: object) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_auth_provider="fake",
        chefclaw_fake_owner_id=str(OWNER_ID),
        chefclaw_image_generator="sprite",
        gemini_model="gemini-2.5-flash",
        gemini_media_resolution="low",
        monthly_llm_budget_usd="10",
        gemini_api_key="",  # a secret left unset ⇒ configured=false
        **overrides,
    )
    return app


async def test_get_config_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_read(sm) -> dict[str, str]:
        return {"chefclaw_image_generator": "fake"}  # one override active

    monkeypatch.setattr(config_service, "read_overrides", fake_read)
    async with _client(_admin_app()) as client:
        resp = await client.get("/api/admin/config")
    assert resp.status_code == 200
    body = resp.json()

    by_key = {item["key"]: item for item in body["runtime_policy"]}
    assert len(by_key) == 8
    # The overridden flag: source=override, effective == override.
    cover = by_key["chefclaw_image_generator"]
    assert cover["source"] == "override"
    assert cover["override_value"] == "fake"
    assert cover["effective_value"] == "fake"
    assert cover["env_value"] == "sprite"
    assert cover["choices"] == ["sprite", "fake", "gemini"]
    # A non-overridden flag inherits env.
    model = by_key["gemini_model"]
    assert model["source"] == "env"
    assert model["override_value"] is None
    assert model["effective_value"] == "gemini-2.5-flash"

    # Secrets are STATUS ONLY — never a value.
    secrets = {s["key"]: s["configured"] for s in body["secrets"]}
    assert secrets["gemini_api_key"] is False
    assert "value" not in body["secrets"][0]
    # Infra is read-only values.
    infra = {i["key"]: i for i in body["infra"]}
    assert infra["chefclaw_auth_provider"]["value"] == "fake"
    assert infra["chefclaw_auth_provider"]["requires_restart"] is True


async def test_patch_valid_returns_updated_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_apply(sm, updates, *, changed_by, base) -> None:
        captured["updates"] = updates
        captured["changed_by"] = changed_by

    async def fake_read(sm) -> dict[str, str]:
        return {"chefclaw_image_generator": "gemini"}  # the applied state

    monkeypatch.setattr(config_service, "apply_changes", fake_apply)
    monkeypatch.setattr(config_service, "read_overrides", fake_read)
    async with _client(_admin_app()) as client:
        resp = await client.patch(
            "/api/admin/config", json={"updates": {"chefclaw_image_generator": "gemini"}}
        )
    assert resp.status_code == 200
    assert captured["updates"] == {"chefclaw_image_generator": "gemini"}
    assert captured["changed_by"] == OWNER_ID
    by_key = {i["key"]: i for i in resp.json()["runtime_policy"]}
    assert by_key["chefclaw_image_generator"]["effective_value"] == "gemini"


async def test_patch_clear_sends_null(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_apply(sm, updates, *, changed_by, base) -> None:
        captured["updates"] = updates

    async def fake_read(sm) -> dict[str, str]:
        return {}

    monkeypatch.setattr(config_service, "apply_changes", fake_apply)
    monkeypatch.setattr(config_service, "read_overrides", fake_read)
    async with _client(_admin_app()) as client:
        resp = await client.patch(
            "/api/admin/config", json={"updates": {"monthly_llm_budget_usd": None}}
        )
    assert resp.status_code == 200
    # null reached the service as None (clear ⇒ revert to env).
    assert captured["updates"] == {"monthly_llm_budget_usd": None}


async def test_patch_secret_key_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    # Real apply_changes runs (rejects in step 1, before any DB touch): a secret
    # is not a registered key ⇒ 422, and it never reaches the table.
    called = False

    async def fake_read(sm) -> dict[str, str]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(config_service, "read_overrides", fake_read)
    async with _client(_admin_app()) as client:
        resp = await client.patch(
            "/api/admin/config", json={"updates": {"gemini_api_key": "x"}}
        )
    assert resp.status_code == 422
    assert resp.json()["error_type"] == "config_invalid"
    assert "gemini_api_key" in resp.json()["detail"]
    assert called is False  # rejected before the post-write re-read


async def test_patch_bad_value_is_422() -> None:
    async with _client(_admin_app()) as client:
        resp = await client.patch(
            "/api/admin/config", json={"updates": {"chefclaw_image_generator": "bogus"}}
        )
    assert resp.status_code == 422
    assert "chefclaw_image_generator" in resp.json()["detail"]


async def test_patch_extra_field_forbidden() -> None:
    # AdminConfigPatch is extra="forbid": a stray top-level field ⇒ FastAPI 422.
    async with _client(_admin_app()) as client:
        resp = await client.patch(
            "/api/admin/config", json={"updates": {}, "sneaky": 1}
        )
    assert resp.status_code == 422


async def test_config_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    async def non_admin(owner_id: uuid.UUID) -> auth.Account:
        return auth.Account(id=OWNER_ID, name="u", email="u@x", is_admin=False)

    monkeypatch.setattr(auth, "fetch_account", non_admin)
    async with _client(_admin_app()) as client:
        get_resp = await client.get("/api/admin/config")
        patch_resp = await client.patch("/api/admin/config", json={"updates": {}})
    assert get_resp.status_code == 403
    assert patch_resp.status_code == 403
