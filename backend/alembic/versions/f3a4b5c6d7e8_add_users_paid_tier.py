"""add users.paid_tier (per-user paid Gemini tier)

Revision ID: f3a4b5c6d7e8
Revises: c3f0a1b2d4e5
Create Date: 2026-07-07

M3 (ADR 2026-07-07-per-user-budget-caps). Adds the per-user paid-tier flag:
when true, that account's extractions use ``GEMINI_PAID_MODEL`` (gemini-2.5-pro)
instead of the global ``GEMINI_MODEL`` default (gemini-2.5-flash). NOT NULL with
a ``false`` server_default, so every existing row backfills to the free tier —
no data migration, no downtime.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "c3f0a1b2d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "paid_tier",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "paid_tier")
