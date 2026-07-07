"""/api/health auth + shape tests (no real database — see conftest)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chefclaw.app import _backup_status, create_app
from chefclaw.config import Settings, get_settings
from tests.conftest import OWNER_ID, TEST_TOKEN, bearer


async def test_health_401_without_session(unauth_client: AsyncClient, ping_ok: None) -> None:
    """No session cookie ⇒ 401 (cookie-session auth, M2)."""
    response = await unauth_client.get("/api/health")
    assert response.status_code == 401


async def test_health_401_with_invalid_session(unauth_client: AsyncClient, ping_ok: None) -> None:
    """A cookie that resolves to no live session ⇒ 401 (fetch_session_owner_id
    is stubbed to None for unauth_client)."""
    unauth_client.cookies.set("chefclaw_session", "not-a-real-session")
    response = await unauth_client.get("/api/health")
    assert response.status_code == 401


async def test_health_200_full_shape(client: AsyncClient, ping_ok: None) -> None:
    response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "db": "ok",
        "sidecar": "not_configured",
        "cookie_freshness": "not_configured",
        "cookie_set_date": None,
        "backup": "not_configured",  # default state-file path doesn't exist here
        "backup_finished_at": None,
        "extractor": "fake",  # the conftest Settings default
        "model": "fake-extractor",
        "paid_tier": False,
        "spend_month_usd": None,
        # V2-A: caps are null (conftest Settings leave the budget pair unset —
        # fail-closed), the ledger reads are stubbed to None, no lifespan ran
        # (ASGITransport) so the worker task doesn't exist, and Sentry is
        # never initialised in the unit tier.
        "budget_monthly_usd": None,
        "daily_attempt_cap": None,
        "budget_is_personal": False,
        "attempts_today": None,
        "worker": "not_running",
        "sentry_enabled": False,
    }


async def test_health_degraded_when_db_unreachable(
    client: AsyncClient, ping_down: None
) -> None:
    response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "unreachable"


async def test_health_never_raises_on_malformed_sidecar_url(ping_ok: None) -> None:
    """A stray control character in XHS_SIDECAR_URL (classic \\r from a
    Windows-edited env file) raises httpx.InvalidURL — which is NOT an
    HTTPError. Health must report 'unreachable', never 500. The malformed URL
    fails at request build, so no network is ever touched."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_api_token=TEST_TOKEN,
        xhs_sidecar_url="http://xhs:8000\r",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    assert response.json()["sidecar"] == "unreachable"


# ── backup staleness (Phase 4: the health field becomes real) ───────────────


def write_backup_state(path: Path, *, ok: bool = True, age_hours: float = 1.0) -> str:
    finished_at = (datetime.now(UTC) - timedelta(hours=age_hours)).isoformat()
    path.write_text(
        json.dumps(
            {
                "finished_at": finished_at,
                "ok": ok,
                "db_file": "chefclaw-db-test.sql.gpg",
                "media_file": "chefclaw-media-test.tar.gz.gpg",
                "db_bytes": 12345,
                "media_bytes": 67890,
            }
        ),
        encoding="utf-8",
    )
    return finished_at


def settings_with_state(path: Path) -> Settings:
    return Settings(chefclaw_api_token=TEST_TOKEN, backup_state_file=str(path))


def test_backup_status_missing_file_is_not_configured(tmp_path: Path) -> None:
    settings = settings_with_state(tmp_path / "does-not-exist.json")
    assert _backup_status(settings) == ("not_configured", None)


def test_backup_status_recent_ok_is_fresh(tmp_path: Path) -> None:
    state = tmp_path / "last-backup.json"
    finished_at = write_backup_state(state, ok=True, age_hours=1)
    assert _backup_status(settings_with_state(state)) == ("fresh", finished_at)


def test_backup_status_old_backup_is_stale(tmp_path: Path) -> None:
    """>= 26h means a daily launchd run was missed — warn."""
    state = tmp_path / "last-backup.json"
    finished_at = write_backup_state(state, ok=True, age_hours=27)
    assert _backup_status(settings_with_state(state)) == ("stale", finished_at)


def test_backup_status_failed_backup_is_stale_even_when_recent(tmp_path: Path) -> None:
    state = tmp_path / "last-backup.json"
    finished_at = write_backup_state(state, ok=False, age_hours=0.1)
    assert _backup_status(settings_with_state(state)) == ("stale", finished_at)


def test_backup_status_unparseable_state_is_stale_never_raises(tmp_path: Path) -> None:
    """Garbage in the state file must warn ('stale'), never 500 the endpoint."""
    state = tmp_path / "last-backup.json"
    state.write_text("not json at all {", encoding="utf-8")
    assert _backup_status(settings_with_state(state)) == ("stale", None)


def test_backup_status_existing_but_unreadable_state_is_stale(tmp_path: Path) -> None:
    """A state path that EXISTS but cannot be read (here: a directory in its
    place; same OSError family as a permission error) is a broken backup
    signal — 'stale', never 'not_configured' (which would tell the operator
    to set up backups they already have)."""
    state = tmp_path / "last-backup.json"
    state.mkdir()  # reading a directory raises IsADirectoryError (an OSError)
    assert _backup_status(settings_with_state(state)) == ("stale", None)


def test_backup_status_future_timestamp_is_stale(tmp_path: Path) -> None:
    """A finished_at in the future (beyond drift slack) is corrupted state or
    serious clock skew — it must warn, not read 'fresh' until the bogus date
    arrives."""
    state = tmp_path / "last-backup.json"
    finished_at = write_backup_state(state, ok=True, age_hours=-2)  # 2h ahead
    assert _backup_status(settings_with_state(state)) == ("stale", finished_at)


def test_backup_status_small_future_drift_is_tolerated(tmp_path: Path) -> None:
    """Minutes of container-vs-host clock drift (laptop sleep) must not flap
    the readout to 'stale'."""
    state = tmp_path / "last-backup.json"
    finished_at = write_backup_state(state, ok=True, age_hours=-0.2)  # 12 min
    assert _backup_status(settings_with_state(state)) == ("fresh", finished_at)


def test_backup_status_naive_timestamp_treated_as_utc(tmp_path: Path) -> None:
    state = tmp_path / "last-backup.json"
    naive = datetime.now(UTC).replace(tzinfo=None).isoformat()
    state.write_text(json.dumps({"finished_at": naive, "ok": True}), encoding="utf-8")
    assert _backup_status(settings_with_state(state)) == ("fresh", naive)


async def test_health_reports_fresh_backup_and_live_extractor(
    ping_ok: None, tmp_path: Path
) -> None:
    """Endpoint-level: backup + extractor/model come from settings, not stubs."""
    state = tmp_path / "last-backup.json"
    finished_at = write_backup_state(state, ok=True, age_hours=2)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_api_token=TEST_TOKEN,
        backup_state_file=str(state),
        chefclaw_extractor="gemini",
        gemini_model="gemini-test-model",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["backup"] == "fresh"
    assert body["backup_finished_at"] == finished_at
    assert body["extractor"] == "gemini"
    assert body["model"] == "gemini-test-model"


async def test_health_surfaces_stale_backup(ping_ok: None, tmp_path: Path) -> None:
    """Phase-4 acceptance (plan §9): /api/health surfaces a STALE backup —
    endpoint-level, through the real dependency wiring."""
    state = tmp_path / "last-backup.json"
    finished_at = write_backup_state(state, ok=True, age_hours=48)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_api_token=TEST_TOKEN,
        backup_state_file=str(state),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["backup"] == "stale"
    assert body["backup_finished_at"] == finished_at


# ── cookie set-date (Phase 4 Settings screen shows WHEN beside the bucket) ──


async def test_health_exposes_cookie_set_date_with_bucket(ping_ok: None) -> None:
    """A configured XHS_COOKIE_SET_DATE surfaces verbatim next to its derived
    freshness bucket (30 days old ⇒ 'stale' regardless of when this runs)."""
    set_date = (datetime.now(UTC).date() - timedelta(days=30)).isoformat()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_api_token=TEST_TOKEN,
        xhs_cookie_set_date=set_date,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["cookie_freshness"] == "stale"
    assert body["cookie_set_date"] == set_date


async def test_health_unparseable_set_date_still_surfaces(ping_ok: None) -> None:
    """Garbage in XHS_COOKIE_SET_DATE warns ('stale') but the raw value still
    shows — seeing the typo in the UI is the fastest fix."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_api_token=TEST_TOKEN,
        xhs_cookie_set_date="not-a-date",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["cookie_freshness"] == "stale"
    assert body["cookie_set_date"] == "not-a-date"


async def test_health_owner_scoped_readouts_resolve(client: AsyncClient, ping_ok: None) -> None:
    """require_owner (fake mode) resolves the owner so the owner-scoped health
    readouts render — the M2 replacement for the deleted _cached_owner_id path
    (the require_owner session path is covered in test_auth.py)."""
    response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── M3: /api/health surfaces the EFFECTIVE (per-user-or-global) cap ──────────


def _budget_app() -> FastAPI:
    """A fake-auth app with the global env budget configured (so parse_budget
    succeeds and the per-user override read runs)."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_auth_provider="fake",
        chefclaw_fake_owner_id=str(OWNER_ID),
        monthly_llm_budget_usd="10",
        max_extraction_attempts_per_day="25",
    )
    return app


async def test_health_reports_global_cap_when_no_per_user_override(ping_ok: None) -> None:
    """No per-user override (columns NULL) ⇒ the global env cap shows and
    budget_is_personal is False (conftest stubs _user_budget_caps → None,None)."""
    transport = ASGITransport(app=_budget_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    body = response.json()
    assert body["budget_monthly_usd"] == 10.0
    assert body["daily_attempt_cap"] == 25
    assert body["budget_is_personal"] is False


async def test_health_surfaces_per_user_override(
    ping_ok: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-user override REPLACES the global cap in the readout and flags
    budget_is_personal so the Settings bar can label it a personal cap."""
    from decimal import Decimal

    from chefclaw import app as app_module

    async def fake_caps(owner_id):
        return Decimal("3.00"), 5

    monkeypatch.setattr(app_module, "_user_budget_caps", fake_caps)
    transport = ASGITransport(app=_budget_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    body = response.json()
    assert body["budget_monthly_usd"] == 3.0  # the per-user cap, not the global 10
    assert body["daily_attempt_cap"] == 5
    assert body["budget_is_personal"] is True


async def test_health_reports_paid_tier_owner_effective_model(
    ping_ok: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A paid-tier owner's health readout shows the PAID model + paid_tier True;
    the model field is the caller's effective model, not the global default."""
    from chefclaw import app as app_module

    async def paid(owner_id):
        return True

    monkeypatch.setattr(app_module, "_owner_paid_tier", paid)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_auth_provider="fake",
        chefclaw_fake_owner_id=str(OWNER_ID),
        chefclaw_extractor="gemini",
        gemini_api_key="k",
        gemini_model="gemini-2.5-flash",
        gemini_paid_model="gemini-2.5-pro",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    body = response.json()
    assert body["paid_tier"] is True
    assert body["model"] == "gemini-2.5-pro"


async def test_health_free_tier_owner_shows_global_model(ping_ok: None) -> None:
    """A free-tier owner (conftest stubs _owner_paid_tier → False) shows the
    global default model and paid_tier False."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        chefclaw_auth_provider="fake",
        chefclaw_fake_owner_id=str(OWNER_ID),
        chefclaw_extractor="gemini",
        gemini_api_key="k",
        gemini_model="gemini-2.5-flash",
        gemini_paid_model="gemini-2.5-pro",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    body = response.json()
    assert body["paid_tier"] is False
    assert body["model"] == "gemini-2.5-flash"
