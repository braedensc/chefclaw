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
    # M3-readiness per-user caps: added now so the shape is stable, but UNUSED by
    # M2 logic (spend.check_budget still reads the GLOBAL env budget in M2 —
    # all users share one pool until M3 wires these in). NULL = no per-user cap.
    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    max_attempts_per_day: Mapped[int | None] = mapped_column(Integer)
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


class Session(Base):
    """A server-side opaque session (M2). The cookie carries a random 256-bit
    token; only its sha256 ``token_hash`` is stored, so a DB dump can't be
    replayed. Lookups are ``WHERE token_hash = sha256(cookie) AND expires_at >
    now()``. Instant revocation (logout / de-invite) is a DELETE of the row —
    the reason this is stateful, not a JWT."""

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
