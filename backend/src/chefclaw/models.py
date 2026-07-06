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


class JobStatus(enum.StrEnum):
    """Enumerated jobs.status values."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    STORED = "stored"
    FAILED = "failed"


def _status_check(status_enum: type[enum.StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in status_enum)
    return f"status IN ({values})"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class Recipe(Base):
    __tablename__ = "recipes"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "canonical_id",
            "dish_index",
            name="uq_recipes_platform_canonical_dish",
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
    # Poster keyframe in the media archive (server filesystem path). NEVER
    # exposed by the API — RecipeSummary derives has_cover from it and the
    # /cover endpoint streams the file. NULL = no cover (best-effort stage).
    cover_path: Mapped[str | None] = mapped_column(Text)
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
