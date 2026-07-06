"""walking skeleton: users, recipes, jobs, llm_spend

Revision ID: 8c1f5d2a9b40
Revises:
Create Date: 2026-07-06

Handwritten migration #1. Every primary key defaults to the database-native
``uuidv7()`` (PostgreSQL 18). Seeds exactly one owner row (name 'owner');
a deterministic id is not required — the uuidv7 default is fine.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c1f5d2a9b40"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECIPE_STATUSES = "'extracting', 'stored', 'failed'"
JOB_STATUSES = "'pending', 'downloading', 'extracting', 'validating', 'stored', 'failed'"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )

    op.create_table(
        "recipes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=True),
        sa.Column("title_original", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("canonical_id", sa.Text(), nullable=False),
        sa.Column("dish_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'stored'"), nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("user_notes", sa.Text(), nullable=True),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column(
            "extraction_meta",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recipes"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_recipes_owner_id_users"),
        sa.UniqueConstraint(
            "platform",
            "canonical_id",
            "dish_index",
            name="uq_recipes_platform_canonical_dish",
        ),
        sa.CheckConstraint(f"status IN ({RECIPE_STATUSES})", name=op.f("ck_recipes_status_enum")),
    )
    op.create_index("ix_recipes_owner_id", "recipes", ["owner_id"])

    op.create_table(
        "jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("canonical_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "result_recipe_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_jobs_owner_id_users"),
        sa.CheckConstraint(f"status IN ({JOB_STATUSES})", name=op.f("ck_jobs_status_enum")),
    )
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"])
    op.create_index("ix_jobs_canonical_id", "jobs", ["canonical_id"])

    op.create_table(
        "llm_spend",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_thinking", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_llm_spend"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_llm_spend_job_id_jobs"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_llm_spend_owner_id_users"),
    )
    op.create_index("ix_llm_spend_owner_id_created_at", "llm_spend", ["owner_id", "created_at"])

    # Seed the single owner row (id via the uuidv7() default — deterministic
    # id deliberately not required; auth resolves the owner by LIMIT 1).
    op.execute("INSERT INTO users (name) VALUES ('owner')")


def downgrade() -> None:
    op.drop_index("ix_llm_spend_owner_id_created_at", table_name="llm_spend")
    op.drop_table("llm_spend")
    op.drop_index("ix_jobs_canonical_id", table_name="jobs")
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_recipes_owner_id", table_name="recipes")
    op.drop_table("recipes")
    op.drop_table("users")
