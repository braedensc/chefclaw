"""app_config runtime-policy overrides + config_audit

Revision ID: b2f4a6c8d0e1
Revises: a1c2e3f4b5d6
Create Date: 2026-07-07

ADR 2026-07-07-admin-config-panel. Two additive, data-safe tables (no touch to
existing rows):

- ``app_config`` — a key/value override for a CLOSED allowlist of runtime-policy
  flags (the allowlist lives in ``chefclaw.app_config``, NOT a DB CHECK, so
  adding a flag never needs a migration). A row OVERRIDES the env ``Settings``
  field of the same name at read time. NO ``owner_id`` — a system/admin
  artifact, like ``invites``; ``updated_by`` FKs the admin who set it.
- ``config_audit`` — append-only history of every change (old→new, which admin).
  No FK to ``app_config`` (its rows come and go); values are never secret.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2f4a6c8d0e1"
down_revision: str | None = "a1c2e3f4b5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name="fk_app_config_updated_by_users"
        ),
        sa.PrimaryKeyConstraint("key", name="pk_app_config"),
    )
    op.create_table(
        "config_audit",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"], ["users.id"], name="fk_config_audit_changed_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_config_audit"),
    )
    op.create_index("ix_config_audit_created_at", "config_audit", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_config_audit_created_at", table_name="config_audit")
    op.drop_table("config_audit")
    op.drop_table("app_config")
