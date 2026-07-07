"""add recipes illustration + estimated columns

Revision ID: f2a7c91b3e08
Revises: 8c1f5d2a9b40
Create Date: 2026-07-06

V2-E (2026-07-06): the card cover is a GENERATED cartoon illustration built
from text fields (never a video keyframe), and cards carry derived spiciness +
difficulty estimates. Three nullable columns on ``recipes``:

- ``image_url``  — the stored illustration's server filesystem path (inside the
  media archive). NEVER exposed raw — the API derives a ``has_image`` boolean
  and streams the file via the /image route. NULL = no illustration yet
  (best-effort stage; the startup backfill heals misses).
- ``image_style_version`` — which fixed style block produced the image
  (e.g. "cartoon-v1"), so a future restyle can target stale versions.
- ``estimated`` — the DERIVED-attributes blob (spiciness_level / difficulty_
  level, 0–3, source:"derived"). Kept SEPARATE from the raw ``document`` so it
  never overwrites verbatim captures (Hard Rule 7), same posture as the
  reserved nutrition_ref. NULL when the extraction supplied no estimates.

(This migration is unmerged — it replaces the earlier cover_path migration
that never left this branch; cover_path is dropped from the schema entirely.)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a7c91b3e08"
down_revision: str | None = "8c1f5d2a9b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("image_url", sa.Text(), nullable=True))
    op.add_column("recipes", sa.Column("image_style_version", sa.Text(), nullable=True))
    op.add_column(
        "recipes",
        sa.Column("estimated", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recipes", "estimated")
    op.drop_column("recipes", "image_style_version")
    op.drop_column("recipes", "image_url")
