"""owner-scope the recipe dedupe UNIQUE constraint

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-07

M2 (ADR 2026-07-07-m2-accounts-and-invites; the Path-B dedupe pre-commitment).
Swaps the recipe dedupe constraint from UNIQUE(platform, canonical_id,
dish_index) — a CROSS-TENANT collision, where two owners who extract the same
canonical video fight over one row — to UNIQUE(owner_id, platform,
canonical_id, dish_index). All three repo.py dedupe lookups are owner-scoped to
match.

DATA-SAFE TODAY: every existing row shares the single seed owner, so the wider
constraint holds on the current data with zero conflicts.

⚠️ ONE-WAY DOOR: this ``upgrade`` is safe to reverse ONLY while at most one
owner exists. Once a REAL second user has extracted the same canonical video as
another user, two rows share (platform, canonical_id, dish_index) and the
``downgrade`` below — which recreates the 3-column constraint — WILL FAIL with a
duplicate-key violation. That is intentional: reverting owner-scoped dedupe once
multiple tenants exist would be a cross-tenant data hazard, so the migration
refuses rather than silently merging owners' rows.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_recipes_platform_canonical_dish", "recipes", type_="unique")
    op.create_unique_constraint(
        op.f("uq_recipes_owner_platform_canonical_dish"),
        "recipes",
        ["owner_id", "platform", "canonical_id", "dish_index"],
    )


def downgrade() -> None:
    # ⚠️ Fails once a real second user shares a canonical id with another user
    # (see the module docstring — this is a deliberate one-way door).
    op.drop_constraint("uq_recipes_owner_platform_canonical_dish", "recipes", type_="unique")
    op.create_unique_constraint(
        op.f("uq_recipes_platform_canonical_dish"),
        "recipes",
        ["platform", "canonical_id", "dish_index"],
    )
