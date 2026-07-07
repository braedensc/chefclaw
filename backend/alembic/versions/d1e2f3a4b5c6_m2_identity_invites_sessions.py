"""M2 identity: users identity columns + invites + sessions

Revision ID: d1e2f3a4b5c6
Revises: a3d9e1f4c72b
Create Date: 2026-07-07

M2 (accounts & invites, ADR 2026-07-07-m2-accounts-and-invites). Additive and
data-safe on the current single-owner database:

- ``users`` gains the OAuth-identity columns. ``email`` is added NULLABLE first,
  the single seed owner row is backfilled (``email='owner@localhost'``,
  ``is_admin=true``, ``display_name=name``), THEN email is set NOT NULL + UNIQUE.
  ``(oauth_provider, oauth_subject)`` is partial-unique (only once bound). The
  per-user budget columns are M3-readiness — added but UNUSED by M2 logic.
- ``invites`` — admin-issued, invite-only signup. NO owner_id (an admin/system
  artifact). Only the sha256 ``token_hash`` is stored, never the raw token.
- ``sessions`` — server-side opaque sessions; only the sha256 ``token_hash`` is
  stored. Instant revocation is a row DELETE (the reason this is stateful).

The recipe dedupe UNIQUE-constraint swap is the SEPARATE next revision
(owner_scope_recipe_dedupe) so the one-way-door migration stands alone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "a3d9e1f4c72b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_STATUSES = "'active', 'disabled'"
INVITE_STATUSES = "'pending', 'accepted', 'revoked'"


def upgrade() -> None:
    # ── users: identity columns (email nullable first, then backfill) ────────
    op.add_column("users", sa.Column("email", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("oauth_provider", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("oauth_subject", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("users", sa.Column("monthly_budget_usd", sa.Numeric(10, 2), nullable=True))
    op.add_column("users", sa.Column("max_attempts_per_day", sa.Integer(), nullable=True))

    # Backfill the single seed owner (migration #1 inserted exactly one row):
    # it becomes the admin and gets a placeholder email so the NOT NULL + UNIQUE
    # can land. The real Google identity attaches at first sign-in
    # (bootstrap-claim, gated on bootstrap_admin_email — PR 3).
    op.execute(
        "UPDATE users "
        "SET email = 'owner@localhost', is_admin = true, display_name = name "
        "WHERE email IS NULL"
    )

    op.alter_column("users", "email", nullable=False)
    op.create_unique_constraint(op.f("uq_users_email"), "users", ["email"])
    # One account per BOUND OAuth identity — partial so the pre-claim seed row
    # (both columns null) doesn't collide.
    op.create_index(
        "uq_users_oauth_identity",
        "users",
        ["oauth_provider", "oauth_subject"],
        unique=True,
        postgresql_where=sa.text("oauth_provider IS NOT NULL AND oauth_subject IS NOT NULL"),
    )
    op.create_check_constraint(
        op.f("ck_users_status_enum"), "users", f"status IN ({USER_STATUSES})"
    )

    # ── invites ──────────────────────────────────────────────────────────────
    op.create_table(
        "invites",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepted_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_invites"),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["users.id"], name="fk_invites_invited_by_users"
        ),
        sa.ForeignKeyConstraint(
            ["accepted_user_id"], ["users.id"], name="fk_invites_accepted_user_id_users"
        ),
        sa.CheckConstraint(
            f"status IN ({INVITE_STATUSES})", name=op.f("ck_invites_status_enum")
        ),
    )
    # At most one PENDING invite per email (re-issuing rotates the same row);
    # accepted/revoked rows linger for history and don't block a re-invite.
    op.create_index(
        "uq_invites_email_pending",
        "invites",
        ["email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_invites_token_hash", "invites", ["token_hash"])

    # ── sessions ─────────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_sessions_owner_id_users"),
        # UNIQUE token_hash — its index IS the session-lookup path.
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_index("ix_invites_token_hash", table_name="invites")
    op.drop_index("uq_invites_email_pending", table_name="invites")
    op.drop_table("invites")
    op.drop_constraint(op.f("ck_users_status_enum"), "users", type_="check")
    op.drop_index("uq_users_oauth_identity", table_name="users")
    op.drop_constraint(op.f("uq_users_email"), "users", type_="unique")
    op.drop_column("users", "max_attempts_per_day")
    op.drop_column("users", "monthly_budget_usd")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "status")
    op.drop_column("users", "display_name")
    op.drop_column("users", "oauth_subject")
    op.drop_column("users", "oauth_provider")
    op.drop_column("users", "email")
