"""Runtime-policy config overrides (ADR 2026-07-07-admin-config-panel).

A tiny ``app_config`` key/value table OVERRIDES the environment ``Settings`` at
read time, for a CLOSED allowlist of runtime-policy flags — never secrets, never
infra. This module is the single source of truth for that allowlist (the DB
table is dumb text): which keys are editable, how a stored string coerces to its
``Settings`` field type, and how a proposed write is validated.

Row present = override active (the value may be ``""`` — an EXPLICIT empty that
shadows the env value: for budget that means "disable paid calls", for the
resolution ceiling "escalation off"). Row absent = inherit the env value.

Secrets NEVER appear here (Hard Rules 2/3/4). ``PATCH`` rejects any key not in
:data:`EDITABLE_KEYS`, and :func:`load_overrides` ignores a row whose key is not
registered (a removed flag's stale row is inert). The overlay is applied with
``Settings.model_copy(update=...)`` — the same idiom
``extractors.extractor_settings_for_tier`` already uses — so the ~10 read sites
never change; they keep reading ``settings.<field>`` and simply receive the
effective object.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chefclaw.config import Settings
from chefclaw.models import AppConfig

Category = Literal["covers", "models", "budget"]
Control = Literal["enum", "bool", "text", "budget"]

_RESOLUTIONS = ("low", "medium", "high")
_RESOLUTION_RANK = {name: rank for rank, name in enumerate(_RESOLUTIONS)}
_COVER_MODES = ("sprite", "fake", "gemini")


# ── validators / coercers (stored text ⇆ Settings field) ─────────────────────


def _one_of(choices: tuple[str, ...]) -> Callable[[str], str | None]:
    joined = ", ".join(repr(c) for c in choices)

    def _validate(raw: str) -> str | None:
        return None if raw in choices else f"must be one of {joined}"

    return _validate


def _coerce_bool(raw: str) -> bool:
    return raw.strip().lower() == "true"


def _validate_bool(raw: str) -> str | None:
    return None if raw.strip().lower() in ("true", "false") else "must be 'true' or 'false'"


def _validate_nonempty(raw: str) -> str | None:
    return None if raw.strip() else "must not be empty"


def _validate_budget_usd(raw: str) -> str | None:
    # Empty is VALID and meaningful: it DISABLES paid calls (fail-closed, §16.8),
    # exactly as an unset env var does. Anything non-empty must be a positive
    # amount so the panel rejects a typo before it can silently mis-gate spend.
    if raw.strip() == "":
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation:
        return "must be a number, or empty to disable paid calls"
    if not value.is_finite() or value <= 0:
        return "must be a positive dollar amount, or empty to disable paid calls"
    return None


def _validate_daily_cap(raw: str) -> str | None:
    if raw.strip() == "":
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return "must be a whole number, or empty to disable paid calls"
    return None if value > 0 else "must be a positive integer, or empty to disable paid calls"


def _validate_resolution_max(raw: str) -> str | None:
    # Empty = escalation OFF. A non-empty value must be a known resolution; the
    # "strictly above the base" cross-field rule is checked by
    # :func:`validate_effective` over the CANDIDATE settings at the endpoint.
    if raw.strip() == "":
        return None
    joined = ", ".join(repr(r) for r in _RESOLUTIONS)
    return None if raw in _RESOLUTIONS else f"must be empty or one of {joined}"


@dataclass(frozen=True)
class ConfigSpec:
    """One editable runtime-policy flag. ``key`` IS the ``Settings`` field name."""

    key: str
    category: Category
    control: Control
    description: str
    choices: tuple[str, ...] = ()
    # stored text -> python value for ``model_copy`` (identity for str fields).
    coerce: Callable[[str], Any] = str
    # (raw) -> None if a legal value for this field, else a human message.
    validate: Callable[[str], str | None] = field(default=lambda raw: None)


SPECS: tuple[ConfigSpec, ...] = (
    ConfigSpec(
        "chefclaw_image_generator", "covers", "enum",
        "Card cover mode. 'sprite' = inline curated SVG, no spend; "
        "'fake' = canned test blob; 'gemini' = paid generated illustration.",
        choices=_COVER_MODES, validate=_one_of(_COVER_MODES),
    ),
    ConfigSpec(
        "chefclaw_real_covers", "covers", "bool",
        "Global switch for PRIVATE real video-frame covers. Meaningful only in "
        "sprite mode; a per-user grant additionally gates who may SEE a frame.",
        choices=("false", "true"), coerce=_coerce_bool, validate=_validate_bool,
    ),
    ConfigSpec(
        "gemini_model", "models", "text",
        "Global free-tier extraction model id (e.g. gemini-2.5-flash).",
        validate=_validate_nonempty,
    ),
    ConfigSpec(
        "gemini_paid_model", "models", "text",
        "Per-user paid-tier extraction model id (e.g. gemini-2.5-pro).",
        validate=_validate_nonempty,
    ),
    ConfigSpec(
        "gemini_media_resolution", "models", "enum",
        "Base media resolution for extraction (low uses the fewest tokens).",
        choices=_RESOLUTIONS, validate=_one_of(_RESOLUTIONS),
    ),
    ConfigSpec(
        "gemini_media_resolution_max", "models", "enum",
        "One-shot resolution-escalation ceiling. Empty = OFF. Must be strictly "
        "ABOVE the base resolution to enable a single higher-res retry.",
        choices=("", *_RESOLUTIONS), validate=_validate_resolution_max,
    ),
    ConfigSpec(
        "monthly_llm_budget_usd", "budget", "budget",
        "Global monthly LLM budget in USD. EMPTY disables all paid calls "
        "(fail-closed). A per-user cap can only redistribute within this.",
        validate=_validate_budget_usd,
    ),
    ConfigSpec(
        "max_extraction_attempts_per_day", "budget", "budget",
        "Global per-day paid-attempt cap (counts every attempt, including "
        "failures). EMPTY disables all paid calls (fail-closed).",
        validate=_validate_daily_cap,
    ),
)

SPEC_BY_KEY: dict[str, ConfigSpec] = {spec.key: spec for spec in SPECS}
EDITABLE_KEYS: frozenset[str] = frozenset(SPEC_BY_KEY)


# ── overlay (env Settings + DB overrides ⇒ effective Settings) ───────────────


async def load_overrides(session: AsyncSession) -> dict[str, Any]:
    """The active overrides as ``{settings_field: coerced_value}``. Rows whose
    key is not registered are ignored (defensive against a retired flag)."""
    rows = (await session.execute(select(AppConfig.key, AppConfig.value))).all()
    overrides: dict[str, Any] = {}
    for key, value in rows:
        spec = SPEC_BY_KEY.get(key)
        if spec is not None:
            overrides[key] = spec.coerce(value)
    return overrides


def apply_overrides(base: Settings, overrides: dict[str, Any]) -> Settings:
    """Overlay coerced overrides onto a COPY of ``base`` (never mutates it).
    Only allowlisted, already-coerced fields are ever supplied."""
    return base.model_copy(update=overrides) if overrides else base


async def effective_settings_in(session: AsyncSession, base: Settings) -> Settings:
    """Effective settings using an already-open session (the caller's own, so a
    budget read stays inside the double-spend gate's transaction)."""
    return apply_overrides(base, await load_overrides(session))


async def effective_settings(
    sessionmaker: async_sessionmaker[AsyncSession], base: Settings
) -> Settings:
    """Effective settings, opening a short-lived session of its own."""
    async with sessionmaker() as session:
        return await effective_settings_in(session, base)


def validate_effective(settings: Settings) -> str | None:
    """Cross-field guards mirrored from the adapter constructors, run over the
    CANDIDATE effective settings BEFORE a write is persisted, so the table can
    never hold a combo that would fail every job. Defense in depth only — the
    ``GeminiExtractor`` constructor still raises per job if one ever slips
    through, so the job fails surfaced and safe, never crashes the worker."""
    base = settings.gemini_media_resolution
    if base not in _RESOLUTION_RANK:
        joined = ", ".join(repr(r) for r in _RESOLUTIONS)
        return f"gemini_media_resolution must be one of {joined}"
    ceiling = settings.gemini_media_resolution_max
    if ceiling:
        if ceiling not in _RESOLUTION_RANK:
            joined = ", ".join(repr(r) for r in _RESOLUTIONS)
            return f"gemini_media_resolution_max must be empty or one of {joined}"
        if _RESOLUTION_RANK[ceiling] <= _RESOLUTION_RANK[base]:
            return (
                f"gemini_media_resolution_max ({ceiling!r}) must be ABOVE the base "
                f"gemini_media_resolution ({base!r}) to enable escalation"
            )
    return None
