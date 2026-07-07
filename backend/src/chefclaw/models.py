"""SQLAlchemy 2.0 declarative models — migration #1 tables.

`owner_id` lands on every user-owned row from migration #1 (multi-user
insurance, CLAUDE.md Security Model). Dedupe is on canonical identity:
UNIQUE(platform, canonical_id, dish_index) — the raw pasted URL is
provenance only (plan §16 amendment 1).
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names so models and migrations stay in lockstep.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class RecipeStatus(enum.StrEnum):
    """Enumerated recipe.status values (Phase 1, plan §16 amendment 5).

    Default is 'stored': a recipe row is only ever inserted inside the atomic
    multi-dish store transaction (amendment 4), so a row that exists is stored.
    'extracting' and 'failed' are enumerated now for future flows that persist
    placeholder rows.
    """

    EXTRACTING = "extracting"
    STORED = "stored"
    FAILED = "failed"


class JobType(enum.StrEnum):
    """Enumerated jobs.type values (no DB CHECK — the column stays a plain
    string; this enum is the code-side source of truth). ``illustration`` is
    the V2-E follow-up: a retriable, on-demand-regeneratable cover-image job,
    dispatched by the worker WITHOUT the download/extract stages (2026-07-07)."""

    EXTRACT = "extract"
    UPLOAD = "upload"
    ILLUSTRATION = "illustration"


class JobStatus(enum.StrEnum):
    """Enumerated jobs.status values."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    # An illustration job's running stage (skips download/extract). Its terminal
    # states reuse ``stored`` (success) / ``failed`` (surfaced, retriable).
    ILLUSTRATING = "illustrating"
    STORED = "stored"
    FAILED = "failed"


class UserStatus(enum.StrEnum):
    """Enumerated users.status values (M2). ``disabled`` is the de-invite /
    boot state — the owner can revoke a member's access; a disabled user's
    sessions no longer resolve (enforced in PR 2's require_owner)."""

    ACTIVE = "active"
    DISABLED = "disabled"


class InviteStatus(enum.StrEnum):
    """Enumerated invites.status values (M2). An invite is ``pending`` until an
    OAuth sign-in with the matching verified email consumes it (→ ``accepted``),
    or the admin revokes it (→ ``revoked``). Only ONE ``pending`` row per email
    (partial-unique uq_invites_email_pending)."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


def _status_check(status_enum: type[enum.StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in status_enum)
    return f"status IN ({values})"


class User(Base):
    """A real per-user account (M2). ``name`` is the legacy migration-#1 column
    (kept NOT NULL, untouched); M2 adds the identity columns below. Identity is
    Google OAuth: ``email`` (verified, normalized lower/trim) is the invite key,
    and ``(oauth_provider, oauth_subject)`` is the stable binding for returning
    users (email can change; the provider ``sub`` claim does not)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_status_check(UserStatus), name="status_enum"),
        # A single OAuth identity maps to at most one account — but only once
        # bound (both columns non-null); the seed owner row has neither until it
        # is bootstrap-claimed, so the uniqueness is a PARTIAL index.
        Index(
            "uq_users_oauth_identity",
            "oauth_provider",
            "oauth_subject",
            unique=True,
            postgresql_where=text("oauth_provider IS NOT NULL AND oauth_subject IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Verified OAuth email, normalized (lower/trim) — the invite-match key.
    # UNIQUE; NOT NULL after the migration backfills the seed owner row.
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # The OAuth identity binding (provider + its `sub` claim). NULL on the seed
    # owner row until bootstrap-claim; the partial unique index above enforces
    # one account per bound identity.
    oauth_provider: Mapped[str | None] = mapped_column(Text)
    oauth_subject: Mapped[str | None] = mapped_column(Text)
    # Human-facing display name (from the OAuth profile). SEPARATE from the
    # legacy NOT-NULL ``name`` so nothing that reads ``name`` changes.
    display_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )
    # Admin (owner) flag — gates invite management. NEVER settable via a
    # user-facing write (critique M9): only migration backfill or the
    # bootstrap-claim (PR 3) sets it true.
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # M3 per-user caps: a non-NULL column OVERRIDES the global env budget for
    # this account (spend.check_budget); NULL = use the global default.
    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    max_attempts_per_day: Mapped[int | None] = mapped_column(Integer)
    # M3 per-user paid tier: when true this account's extractions use
    # GEMINI_PAID_MODEL (gemini-2.5-pro) instead of the global GEMINI_MODEL
    # (gemini-2.5-flash) default. Set via the admin budget endpoint.
    paid_tier: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # V2-F private real-frame cover grant: when TRUE (and the global
    # CHEFCLAW_REAL_COVERS switch is also on), this user may capture + SEE real
    # finished-dish video frames on their own recipes; otherwise they only ever
    # see sprites. Default FALSE — settable ONLY by the admin/owner (never a
    # user-facing self-write), the second of two gates that keep creator frames
    # off any ungranted viewer. Real frames NEVER cross to another user.
    real_covers_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class Recipe(Base):
    __tablename__ = "recipes"
    __table_args__ = (
        # Dedupe is per-OWNER (M2): two owners who extract the SAME canonical
        # video each get their own recipe rows — the constraint (and every
        # dedupe lookup) is scoped by owner_id. Pre-M2 this was
        # UNIQUE(platform, canonical_id, dish_index) — a cross-tenant collision.
        UniqueConstraint(
            "owner_id",
            "platform",
            "canonical_id",
            "dish_index",
            name="uq_recipes_owner_platform_canonical_dish",
        ),
        CheckConstraint(_status_check(RecipeStatus), name="status_enum"),
        Index("ix_recipes_owner_id", "owner_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    title_en: Mapped[str | None] = mapped_column(Text)
    title_original: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    # Raw pasted URL — provenance only, never used for dedupe.
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_id: Mapped[str] = mapped_column(Text, nullable=False)
    dish_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'stored'")
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    user_notes: Mapped[str | None] = mapped_column(Text)
    # Generated cartoon illustration in the media archive (server filesystem
    # path). NEVER exposed by the API — RecipeSummary derives has_image from it
    # and the /image endpoint streams the file. NULL = no illustration yet
    # (best-effort stage; the startup backfill heals misses).
    image_url: Mapped[str | None] = mapped_column(Text)
    # Which fixed style block produced the illustration (e.g. "cartoon-v1").
    image_style_version: Mapped[str | None] = mapped_column(Text)
    # The assigned curated dish-sprite id (V2-F) — the DEFAULT card cover,
    # rendered INLINE from the bundled SVG catalog (frontend/src/covers), never
    # served via the API. Assigned during extraction (Gemini pick + deterministic
    # keyword fallback) and by the startup backfill; falls back to 'unknown-dish'.
    # Precedence per viewer: a real video frame (image_url, if allowed) → else
    # this sprite. NULL only for rows not yet assigned (a transient pre-backfill
    # state); Hard Rule 7 does not apply — a sprite is decorative, not food data.
    cover_sprite_id: Mapped[str | None] = mapped_column(Text)
    # DERIVED spiciness/difficulty estimates (Hard Rule 7): kept SEPARATE from
    # the raw `document` so it never overwrites verbatim captures — same
    # posture as the reserved nutrition_ref. NULL when the extraction supplied
    # none. Read-only, like the document (never in RecipePatch).
    estimated: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Never user-editable — only tags and user_notes are PATCH-able.
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    extraction_meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_status_check(JobStatus), name="status_enum"),
        Index("ix_jobs_status_created_at", "status", "created_at"),
        Index("ix_jobs_canonical_id", "canonical_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Real, queryable columns (plan §16 amendment 1): the active-job check
    # looks jobs up by canonical id, not by digging in the payload JSON.
    platform: Mapped[str | None] = mapped_column(Text)
    canonical_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_type: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    result_recipe_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=func.now(),
    )


class LlmSpend(Base):
    """Cost ledger — written per model attempt, including failures (plan §10)."""

    __tablename__ = "llm_spend"
    __table_args__ = (Index("ix_llm_spend_owner_id_created_at", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    tokens_thinking: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class CoverMiss(Base):
    """Append-only cover-assignment miss log (V2-F). One row whenever sprite
    assignment falls back to the generic ``unknown-dish`` — either because the
    deterministic matcher found nothing above the confidence threshold, or the
    model suggested an id the catalog doesn't contain. It is the ONLY input the
    future PR-gated "cover gardener" dev pass consumes to author new sprites for
    real gaps; the running server NEVER generates art or writes the repo (that
    would bypass branch protection + CI, a §5 / Hard Rule 5 hole). Nothing here
    is food data (Hard Rule 7 does not apply) — it's diagnostics about a
    decorative default.

    ``recipe_id`` is a soft link (``ON DELETE SET NULL``): recipes are hard-
    deleted, and a diagnostic row must outlive its recipe, not cascade away."""

    __tablename__ = "cover_misses"
    __table_args__ = (Index("ix_cover_misses_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="SET NULL")
    )
    dish_name_en: Mapped[str | None] = mapped_column(Text)
    dish_name_original: Mapped[str | None] = mapped_column(Text)
    cuisine_type: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    # The raw id the model suggested when it was NOT a known catalog id (else
    # NULL — a model miss vs. a genuine no-match are distinguishable downstream).
    suggested_sprite_id: Mapped[str | None] = mapped_column(Text)
    # What assignment actually resolved to (today always 'unknown-dish', but
    # recorded so a future threshold change stays legible in the log).
    resolved_sprite_id: Mapped[str] = mapped_column(Text, nullable=False)
    # The best deterministic-match score (0..1), NULL when there was no candidate.
    score: Mapped[float | None] = mapped_column(Float)
    # Why it missed: 'no_match' | 'low_confidence' | 'unknown_model_id'.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class Invite(Base):
    """An admin-issued invite to one email (M2). Signup is invite-only: an OAuth
    sign-in activates an account ONLY when the verified email matches a
    ``pending`` invite (consumed → ``accepted`` in the same transaction as the
    user create). Deliberately NO ``owner_id`` — an invite is an admin/system
    artifact, not a user-owned row. The raw invite token is NEVER stored (only
    its sha256 ``token_hash``); it exists in memory only during create."""

    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint(_status_check(InviteStatus), name="status_enum"),
        # At most ONE pending invite per email (re-issuing rotates the same
        # row). Accepted/revoked rows linger for history and don't block a
        # future re-invite — hence the PARTIAL unique.
        Index(
            "uq_invites_email_pending",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_invites_token_hash", "token_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    # Invited email, normalized (lower/trim) — matched against the verified
    # OAuth email at activation with the SAME normalization (critique M5).
    email: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 hex of the raw activation token (never the raw token — critique).
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    invited_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class RequestEvent(Base):
    """Append-only request-rate event (V2-D security audit). One row per served
    request against a rate-limited surface, keyed by a coarse identity string:
    ``session:<sha256(cookie)>`` for an authed cookie, ``ip:<addr>`` for the
    public/pre-auth endpoints. The trailing-window COUNT over ``key`` IS the
    throttle — no mutable counter to race, no cron to reset (kit append-only
    pattern, docs/SECURITY.md). Deliberately NO FK to sessions/users: a logout
    DELETEs the session row, but its rate events linger harmlessly (append-only
    log lifecycle never conflicts with record lifecycle — docs/SECURITY.md)."""

    __tablename__ = "request_events"
    __table_args__ = (Index("ix_request_events_key_created_at", "key", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class Session(Base):
    """A server-side opaque session (M2). The cookie carries a random 256-bit
    token; only its sha256 ``token_hash`` is stored, so a DB dump can't be
    replayed. Lookups are ``WHERE token_hash = sha256(cookie) AND expires_at >
    now()`` (plus an idle-timeout check on ``last_seen_at`` — V2-D). Instant
    revocation (logout / de-invite) is a DELETE of the row — the reason this is
    stateful, not a JWT."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # sha256 hex of the raw cookie token. UNIQUE — its index is the lookup path
    # (no separate index needed).
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    # Absolute expiry cap (session_ttl_hours from config, PR 2).
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    # Throttled write (only when now - last_seen_at > N min) so an authed
    # request doesn't write on every hit (critique M8 perf note).
    last_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class AppConfig(Base):
    """A runtime-policy config OVERRIDE (ADR 2026-07-07-admin-config-panel). One
    row per overridden key from the CLOSED allowlist in ``chefclaw.app_config``;
    its ``value`` string OVERRIDES the corresponding env ``Settings`` field at
    read time. Row present = override active (the value may be ``""`` — an
    EXPLICIT empty that shadows the env value; row absent = inherit env).

    Deliberately NO ``owner_id`` — like ``invites``, this is a system/admin
    artifact, not a user-owned row. It NEVER holds a secret: the allowlist is
    non-secret only, ``PATCH`` rejects any unregistered key, and the loader
    ignores a row whose key is not registered."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=func.now(),
    )


class ConfigAudit(Base):
    """Append-only audit of every runtime-policy config change (ADR
    2026-07-07-admin-config-panel). One row per key that actually changed on a
    PATCH: ``old_value`` is NULL when there was no override before, ``new_value``
    is NULL when the override was cleared back to the env default. ``changed_by``
    records WHICH admin (provenance, not ownership). Values are never secret —
    only non-secret allowlisted keys are writable. Same append-only lifecycle as
    ``llm_spend`` / ``request_events``: history outlives any single override
    row (a soft link, no FK to ``app_config``, whose rows come and go)."""

    __tablename__ = "config_audit"
    __table_args__ = (Index("ix_config_audit_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
