"""Runtime-policy override registry + accessor + write-validation (ADR
2026-07-07-admin-config-panel), CI tier — pure functions, NO database. The
DB-backed ``load_overrides``/``effective_settings`` and the audited write path
(persist + config_audit) are the golden tier (``test_admin_config_db.py``)."""

import uuid

import pytest

from chefclaw import app_config
from chefclaw.app_config import SPEC_BY_KEY, apply_overrides, validate_effective
from chefclaw.config import Settings
from chefclaw.services import config as config_service

OWNER = uuid.UUID("01890000-0000-7000-8000-000000000001")


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = dict(
        chefclaw_image_generator="sprite",
        chefclaw_real_covers=False,
        gemini_model="gemini-2.5-flash",
        gemini_paid_model="gemini-2.5-pro",
        gemini_media_resolution="low",
        gemini_media_resolution_max="",
        monthly_llm_budget_usd="10",
        max_extraction_attempts_per_day="25",
    )
    base.update(overrides)
    return Settings(**base)


# ── the allowlist is closed and secret-free ──────────────────────────────────


def test_exactly_eight_editable_flags() -> None:
    assert len(app_config.EDITABLE_KEYS) == 8
    assert set(SPEC_BY_KEY) == app_config.EDITABLE_KEYS


def test_no_secret_is_editable() -> None:
    # The whole point (Hard Rules 2/3/4): a secret can never be an override key.
    assert not (set(config_service.SECRET_STATUS_KEYS) & app_config.EDITABLE_KEYS)


def test_every_editable_key_is_a_real_settings_field() -> None:
    fields = set(Settings.model_fields)
    assert app_config.EDITABLE_KEYS <= fields


# ── overlay (apply_overrides) ─────────────────────────────────────────────────


def test_apply_overrides_copies_and_coerces() -> None:
    base = _settings()
    eff = apply_overrides(
        base, {"chefclaw_image_generator": "fake", "chefclaw_real_covers": True}
    )
    assert eff.chefclaw_image_generator == "fake"
    assert eff.chefclaw_real_covers is True
    # never mutates the base
    assert base.chefclaw_image_generator == "sprite"
    assert base.chefclaw_real_covers is False


def test_apply_overrides_empty_returns_base_unchanged() -> None:
    base = _settings()
    assert apply_overrides(base, {}) is base


def test_bool_coercion_via_spec() -> None:
    spec = SPEC_BY_KEY["chefclaw_real_covers"]
    assert spec.coerce("true") is True
    assert spec.coerce("false") is False
    assert spec.coerce("TRUE") is True


# ── per-value validation (spec.validate) ─────────────────────────────────────


@pytest.mark.parametrize(
    "value,ok",
    [("sprite", True), ("fake", True), ("gemini", True), ("bogus", False), ("", False)],
)
def test_cover_mode_validation(value: str, ok: bool) -> None:
    assert (SPEC_BY_KEY["chefclaw_image_generator"].validate(value) is None) == ok


@pytest.mark.parametrize(
    "value,ok",
    [("true", True), ("false", True), ("TRUE", True), ("yes", False), ("", False)],
)
def test_bool_validation(value: str, ok: bool) -> None:
    assert (SPEC_BY_KEY["chefclaw_real_covers"].validate(value) is None) == ok


@pytest.mark.parametrize(
    "value,ok",
    [("", True), ("10", True), ("0.5", True), ("0", False), ("-1", False), ("abc", False)],
)
def test_budget_validation_empty_is_valid_disable(value: str, ok: bool) -> None:
    # Empty is VALID = disable paid calls (fail-closed); junk/non-positive is not.
    assert (SPEC_BY_KEY["monthly_llm_budget_usd"].validate(value) is None) == ok


@pytest.mark.parametrize(
    "value,ok",
    [("", True), ("25", True), ("1", True), ("0", False), ("-3", False), ("2.5", False)],
)
def test_daily_cap_validation(value: str, ok: bool) -> None:
    assert (SPEC_BY_KEY["max_extraction_attempts_per_day"].validate(value) is None) == ok


@pytest.mark.parametrize(
    "value,ok", [("", True), ("low", True), ("high", True), ("ultra", False)]
)
def test_resolution_max_per_value_validation(value: str, ok: bool) -> None:
    # Per-value: empty (off) or a known resolution. The ABOVE-base cross-field
    # rule is validate_effective's job, tested below.
    assert (SPEC_BY_KEY["gemini_media_resolution_max"].validate(value) is None) == ok


# ── cross-field validation (validate_effective) ──────────────────────────────


def test_resolution_max_above_base_ok() -> None:
    assert (
        validate_effective(
            _settings(gemini_media_resolution="low", gemini_media_resolution_max="high")
        )
        is None
    )


def test_resolution_max_empty_is_off() -> None:
    assert validate_effective(_settings(gemini_media_resolution_max="")) is None


def test_resolution_max_not_above_base_rejected() -> None:
    msg = validate_effective(
        _settings(gemini_media_resolution="high", gemini_media_resolution_max="low")
    )
    assert msg is not None and "ABOVE" in msg


def test_resolution_max_equal_base_rejected() -> None:
    assert (
        validate_effective(
            _settings(gemini_media_resolution="medium", gemini_media_resolution_max="medium")
        )
        is not None
    )


# ── service write-validation (step 1 — no DB reached) ────────────────────────


async def test_apply_changes_rejects_secret_key() -> None:
    # A secret is absent from the registry ⇒ rejected as unknown BEFORE any DB
    # touch (sessionmaker None is never used). Secrets can never be written.
    with pytest.raises(config_service.ConfigValidationError) as ei:
        await config_service.apply_changes(
            None, {"gemini_api_key": "leak"}, changed_by=OWNER, base=_settings()  # type: ignore[arg-type]
        )
    assert "gemini_api_key" in ei.value.errors


async def test_apply_changes_rejects_unknown_key() -> None:
    with pytest.raises(config_service.ConfigValidationError) as ei:
        await config_service.apply_changes(
            None, {"not_a_flag": "x"}, changed_by=OWNER, base=_settings()  # type: ignore[arg-type]
        )
    assert "not_a_flag" in ei.value.errors


async def test_apply_changes_rejects_bad_value() -> None:
    with pytest.raises(config_service.ConfigValidationError) as ei:
        await config_service.apply_changes(
            None,  # type: ignore[arg-type]
            {"chefclaw_image_generator": "bogus"},
            changed_by=OWNER,
            base=_settings(),
        )
    assert "chefclaw_image_generator" in ei.value.errors


def test_render_value_bool_and_str() -> None:
    assert config_service.render_value(True) == "true"
    assert config_service.render_value(False) == "false"
    assert config_service.render_value("gemini-2.5-flash") == "gemini-2.5-flash"
    assert config_service.render_value(300) == "300"
