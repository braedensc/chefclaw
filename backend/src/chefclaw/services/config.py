"""Admin runtime-policy config read/write (ADR 2026-07-07-admin-config-panel).

The write path (:func:`apply_changes`) validates each proposed value against the
``chefclaw.app_config`` registry, REJECTS any key that is not an editable
runtime-policy flag — so a secret can never be written (a secret is simply not in
the registry) — validates the CANDIDATE effective settings for cross-field rules
(the resolution ceiling), then upserts/deletes rows and appends one
``config_audit`` row per key that actually changed, all in ONE transaction. A
structured log line is emitted per change. Nothing is persisted if validation
fails.

The read side exposes only the raw override strings; the router assembles the
full admin view (editable policy + secret status + read-only infra) from the
registry and the env ``Settings``.
"""

import logging
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chefclaw import app_config
from chefclaw.app_config import SPEC_BY_KEY
from chefclaw.config import Settings
from chefclaw.models import AppConfig, ConfigAudit

logger = logging.getLogger("chefclaw.config")


# Secrets shown as STATUS ONLY (configured / not) — NEVER a value (Hard Rules
# 2/3/4). ``chefclaw_fetch_proxy`` rides here too: a residential-proxy URL can
# embed ``user:pass@host`` credentials, so it is status-only, not a shown value.
SECRET_STATUS_KEYS: tuple[str, ...] = (
    "gemini_api_key",
    "google_oauth_client_secret",
    "xhs_cookie",
    "xhs_user_agent",
    "bilibili_cookie",
    "dashscope_api_key",
    "db_password",
    "chefclaw_api_token",
    "chefclaw_fetch_proxy",
)

# Deploy/infra settings surfaced READ-ONLY: env-only, human-changed, need a
# restart. Non-secret values, shown to the admin as context (rendered strings).
INFRA_KEYS: tuple[str, ...] = (
    "chefclaw_auth_provider",
    "google_oauth_client_id",
    "google_oauth_redirect_url",
    "chefclaw_email",
    "email_from",
    "ses_region",
    "public_base_url",
    "bootstrap_admin_email",
    "db_host",
    "db_port",
    "db_user",
    "db_name",
    "chefclaw_extractor",
    "chefclaw_sources",
    "xhs_sidecar_url",
    "media_dir",
    "scratch_dir",
    "sentry_environment",
    "sentry_release",
    "chefclaw_log_format",
    "chefclaw_log_level",
    "backup_state_file",
    "session_ttl_hours",
    "session_idle_timeout_hours",
    "rate_limit_authenticated_per_minute",
    "rate_limit_public_per_minute",
)


class ConfigValidationError(Exception):
    """A proposed config change is invalid (unknown/non-editable key or bad
    value). Carries a per-key message map for a 422 body."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def render_value(value: object) -> str:
    """Render a Settings field value as the panel's canonical string (``bool`` →
    'true'/'false', everything else ``str()``)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


async def read_overrides(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    """The current override strings by key (registered keys only)."""
    async with sessionmaker() as session:
        rows = (await session.execute(select(AppConfig.key, AppConfig.value))).all()
    return {key: value for key, value in rows if key in SPEC_BY_KEY}


async def apply_changes(
    sessionmaker: async_sessionmaker[AsyncSession],
    updates: dict[str, str | None],
    *,
    changed_by: uuid.UUID,
    base: Settings,
) -> None:
    """Validate + persist a batch of runtime-policy changes atomically, auditing
    every key that actually changes. Raises :class:`ConfigValidationError`
    (→ 422) on any unknown/non-editable key or invalid value; on error NOTHING is
    persisted. A ``null`` value CLEARS the override (revert to env); a string SETS
    it (``""`` is a valid explicit shadowing empty — e.g. disable paid calls)."""
    # 1) Key allowlist + per-value validation. A secret is simply absent from the
    #    registry, so it is rejected here as "unknown" — it can never be written.
    errors: dict[str, str] = {}
    for key, value in updates.items():
        spec = SPEC_BY_KEY.get(key)
        if spec is None:
            errors[key] = "unknown or non-editable config key"
        elif value is not None and (msg := spec.validate(value)) is not None:
            errors[key] = msg
    if errors:
        raise ConfigValidationError(errors)

    async with sessionmaker() as session, session.begin():
        current = {
            key: value
            for key, value in (
                await session.execute(select(AppConfig.key, AppConfig.value))
            ).all()
            if key in SPEC_BY_KEY
        }

        # 2) Cross-field validation over the CANDIDATE effective settings (env +
        #    current overrides + this batch). Guards the resolution ceiling so the
        #    table can never hold a combo that would fail every job.
        candidate_raw = dict(current)
        for key, value in updates.items():
            if value is None:
                candidate_raw.pop(key, None)
            else:
                candidate_raw[key] = value
        candidate = app_config.apply_overrides(
            base, {k: SPEC_BY_KEY[k].coerce(v) for k, v in candidate_raw.items()}
        )
        if (cross := app_config.validate_effective(candidate)) is not None:
            raise ConfigValidationError({"gemini_media_resolution_max": cross})

        # 3) Persist + audit — only for keys that ACTUALLY change (a no-op write
        #    audits nothing).
        for key, value in updates.items():
            old = current.get(key)  # None ⇒ was inheriting the env default
            if value is None:
                if key not in current:
                    continue
                await session.execute(delete(AppConfig).where(AppConfig.key == key))
            else:
                if old == value:
                    continue
                await session.execute(
                    pg_insert(AppConfig)
                    .values(key=key, value=value, updated_by=changed_by)
                    .on_conflict_do_update(
                        index_elements=[AppConfig.key],
                        set_={
                            "value": value,
                            "updated_by": changed_by,
                            "updated_at": func.now(),
                        },
                    )
                )
            session.add(
                ConfigAudit(
                    key=key, old_value=old, new_value=value, changed_by=changed_by
                )
            )
            logger.info(
                "config change: %s %r -> %r by %s",
                key,
                old,
                value,
                changed_by,
                extra={"config_key": key, "changed_by": str(changed_by)},
            )
