"""GOLDEN DB tier for the admin config panel (`-m golden`, deselected by default
— never runs in CI). Proves the real ``app_config`` / ``config_audit`` SQL
against a throwaway postgres: an override persists + audits and
``effective_settings`` reflects it; a ``null`` clear deletes the row + audits and
reverts to env; an EXPLICIT empty budget shadows env and stays fail-closed; a
cross-field-invalid batch persists NOTHING; a no-op write audits nothing. Same
throwaway PG as test_worker_db.py / test_users_db.py:

    docker run -d --rm --name chefclaw-golden-pg \
        -p 127.0.0.1:55432:5432 \
        -e POSTGRES_HOST_AUTH_METHOD=trust \
        -e POSTGRES_USER=chefclaw -e POSTGRES_DB=chefclaw_golden \
        postgres:18
    cd backend && uv run pytest -m golden -q
    docker stop chefclaw-golden-pg
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chefclaw import app_config, spend
from chefclaw.config import Settings
from chefclaw.errors import ConfigError
from chefclaw.models import AppConfig, Base, ConfigAudit, User
from chefclaw.services import config as config_service

pytestmark = pytest.mark.golden

GOLDEN_DB_URL = "postgresql+asyncpg://chefclaw@127.0.0.1:55432/chefclaw_golden"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = dict(
        chefclaw_image_generator="sprite",
        gemini_media_resolution="low",
        monthly_llm_budget_usd="10",
        max_extraction_attempts_per_day="25",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
async def sm():
    engine = create_async_engine(GOLDEN_DB_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment guard
        await engine.dispose()
        pytest.skip(
            f"throwaway postgres not reachable on 127.0.0.1:55432 ({exc}) — "
            "see the module docstring for the docker run command"
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _admin(sm) -> uuid.UUID:
    async with sm() as s:
        user = User(name="admin", email=f"admin-{uuid.uuid4()}@x", is_admin=True)
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user.id


async def _audit_rows(sm) -> list[ConfigAudit]:
    async with sm() as s:
        return list(
            (await s.execute(select(ConfigAudit).order_by(ConfigAudit.created_at))).scalars()
        )


async def _override_rows(sm) -> list[AppConfig]:
    async with sm() as s:
        return list((await s.execute(select(AppConfig))).scalars())


async def test_apply_persists_override_and_audits(sm) -> None:
    admin = await _admin(sm)
    base = _settings()
    await config_service.apply_changes(
        sm, {"chefclaw_image_generator": "fake"}, changed_by=admin, base=base
    )

    async with sm() as s:
        eff = await app_config.effective_settings_in(s, base)
    assert eff.chefclaw_image_generator == "fake"  # override beats env

    audits = await _audit_rows(sm)
    assert len(audits) == 1
    assert audits[0].key == "chefclaw_image_generator"
    assert audits[0].old_value is None  # was inheriting env
    assert audits[0].new_value == "fake"
    assert audits[0].changed_by == admin


async def test_clear_reverts_to_env_and_audits(sm) -> None:
    admin = await _admin(sm)
    base = _settings()
    await config_service.apply_changes(
        sm, {"chefclaw_image_generator": "fake"}, changed_by=admin, base=base
    )
    await config_service.apply_changes(
        sm, {"chefclaw_image_generator": None}, changed_by=admin, base=base
    )

    async with sm() as s:
        eff = await app_config.effective_settings_in(s, base)
    assert eff.chefclaw_image_generator == "sprite"  # env default restored
    assert await _override_rows(sm) == []  # row deleted

    audits = await _audit_rows(sm)
    assert len(audits) == 2
    assert audits[1].old_value == "fake"
    assert audits[1].new_value is None  # cleared


async def test_explicit_empty_budget_shadows_env_and_stays_fail_closed(sm) -> None:
    admin = await _admin(sm)
    base = _settings(monthly_llm_budget_usd="10")  # env has a budget
    await config_service.apply_changes(
        sm, {"monthly_llm_budget_usd": ""}, changed_by=admin, base=base
    )

    async with sm() as s:
        eff = await app_config.effective_settings_in(s, base)
    assert eff.monthly_llm_budget_usd == ""  # explicit empty shadows env "10"
    # Fail-closed: an empty budget refuses ALL paid calls (§16.8).
    with pytest.raises(ConfigError):
        spend.parse_budget(eff)


async def test_cross_field_invalid_persists_nothing(sm) -> None:
    admin = await _admin(sm)
    # env base resolution is 'high' ⇒ no ceiling can be strictly above it.
    base = _settings(gemini_media_resolution="high")
    with pytest.raises(config_service.ConfigValidationError):
        await config_service.apply_changes(
            sm, {"gemini_media_resolution_max": "low"}, changed_by=admin, base=base
        )
    assert await _override_rows(sm) == []  # rolled back
    assert await _audit_rows(sm) == []


async def test_noop_write_audits_nothing(sm) -> None:
    admin = await _admin(sm)
    base = _settings()
    await config_service.apply_changes(
        sm, {"chefclaw_image_generator": "fake"}, changed_by=admin, base=base
    )
    # same value again ⇒ no-op: no second override row churn, no audit.
    await config_service.apply_changes(
        sm, {"chefclaw_image_generator": "fake"}, changed_by=admin, base=base
    )
    assert len(await _audit_rows(sm)) == 1
    assert len(await _override_rows(sm)) == 1


async def test_read_overrides_ignores_unregistered_rows(sm) -> None:
    admin = await _admin(sm)
    # A stale row for a retired key must be inert (defensive loader).
    async with sm() as s:
        s.add(AppConfig(key="retired_flag", value="x", updated_by=admin))
        s.add(AppConfig(key="gemini_model", value="gemini-2.5-pro", updated_by=admin))
        await s.commit()
    overrides = await config_service.read_overrides(sm)
    assert overrides == {"gemini_model": "gemini-2.5-pro"}
    async with sm() as s:
        eff = await app_config.effective_settings_in(s, _settings())
    assert eff.gemini_model == "gemini-2.5-pro"
