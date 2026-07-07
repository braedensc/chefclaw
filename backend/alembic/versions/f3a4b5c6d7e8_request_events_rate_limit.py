"""request_events append-only table for API rate limiting

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-07-07

V2-D security audit. Adds the append-only ``request_events`` table backing the
per-session / per-IP request throttle (chefclaw.ratelimit): one row per served
request, keyed by a coarse identity string, and the trailing-window COUNT over
``key`` IS the limit. No mutable counter to race, no cron to reset (kit
append-only pattern, docs/SECURITY.md).

Additive and data-safe: a brand-new table, no touch to existing rows. Deliberately
NO foreign key — a logout DELETEs its session row, but the append-only rate events
must outlive it (append-only log lifecycle never conflicts with record lifecycle).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_request_events"),
    )
    # The trailing-window lookup path: WHERE key = :k AND created_at > :window_start.
    op.create_index(
        "ix_request_events_key_created_at", "request_events", ["key", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_request_events_key_created_at", table_name="request_events")
    op.drop_table("request_events")
