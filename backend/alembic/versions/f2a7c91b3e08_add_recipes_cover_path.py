"""add recipes.cover_path

Revision ID: f2a7c91b3e08
Revises: 8c1f5d2a9b40
Create Date: 2026-07-06

Nullable poster-keyframe path (server filesystem, inside the media archive).
NULL means "no cover" — the worker backfills best-effort on startup, and the
API only ever exposes a derived has_cover boolean, never the path.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a7c91b3e08"
down_revision: str | None = "8c1f5d2a9b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("cover_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("recipes", "cover_path")
