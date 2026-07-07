"""cover sprites + private real-frame grant + miss log

Revision ID: c3f0a1b2d4e5
Revises: e2f3a4b5c6d7
Create Date: 2026-07-07

V2-F cover system (ADR 2026-07-07-cover-system-sprites-and-private-frames):

- ``recipes.cover_sprite_id`` (Text, nullable) — the assigned curated dish-sprite
  id, the DEFAULT card cover rendered inline from the bundled SVG catalog. NULL
  only for rows the backfill hasn't reached yet.
- ``users.real_covers_enabled`` (Boolean, NOT NULL, default false) — the per-user
  half of the two-gate grant that lets an owner capture + SEE private real
  finished-dish video frames (the global CHEFCLAW_REAL_COVERS switch is the other
  half). Both default OFF → pure sprites; a frame never reaches an ungranted
  viewer.
- ``cover_misses`` — append-only diagnostics: one row whenever assignment falls
  back to 'unknown-dish'. The ONLY input the future PR-gated cover gardener
  consumes; the running server never writes the repo. ``recipe_id`` is
  ON DELETE SET NULL so a hard recipe delete doesn't cascade a diagnostic away.

Constraint names are spelled to match the models' metadata naming convention so
autogenerate stays a no-op and downgrade round-trips cleanly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f0a1b2d4e5"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("cover_sprite_id", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "real_covers_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_table(
        "cover_misses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipe_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dish_name_en", sa.Text(), nullable=True),
        sa.Column("dish_name_original", sa.Text(), nullable=True),
        sa.Column("cuisine_type", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("suggested_sprite_id", sa.Text(), nullable=True),
        sa.Column("resolved_sprite_id", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cover_misses"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_cover_misses_owner_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"],
            ["recipes.id"],
            name="fk_cover_misses_recipe_id_recipes",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        op.f("ix_cover_misses_created_at"), "cover_misses", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cover_misses_created_at"), table_name="cover_misses")
    op.drop_table("cover_misses")
    op.drop_column("users", "real_covers_enabled")
    op.drop_column("recipes", "cover_sprite_id")
