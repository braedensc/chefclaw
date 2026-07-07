"""add 'illustrating' to the jobs status CHECK

Revision ID: a3d9e1f4c72b
Revises: f2a7c91b3e08
Create Date: 2026-07-07

V2-E follow-up (2026-07-07): illustration generation is promoted from a
best-effort post-store STAGE to a first-class ``illustration`` job type
(independently retriable + regeneratable on demand). An illustration job's
running stage is the new ``illustrating`` status, so the ``jobs.status`` CHECK
constraint must admit it. The terminal states reuse ``stored`` / ``failed``.

``jobs.type`` gains the ``illustration`` value at the same time, but ``type``
has no CHECK constraint (it never did — the code-side JobType enum is the
source of truth), so only the status CHECK is migrated here.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d9e1f4c72b"
down_revision: str | None = "f2a7c91b3e08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The migration #1 constraint was created with op.f(...) — a LITERAL name, not
# run through the metadata naming convention — so refer to it the same way here
# (a bare string would be re-mangled to ck_jobs_ck_jobs_status_enum).
_CONSTRAINT = op.f("ck_jobs_status_enum")
_OLD_STATUSES = "'pending', 'downloading', 'extracting', 'validating', 'stored', 'failed'"
_NEW_STATUSES = (
    "'pending', 'downloading', 'extracting', 'validating', "
    "'illustrating', 'stored', 'failed'"
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "jobs", type_="check")
    op.create_check_constraint(_CONSTRAINT, "jobs", f"status IN ({_NEW_STATUSES})")


def downgrade() -> None:
    # Any illustration jobs still mid-flight would violate the old CHECK; flip
    # them to 'failed' first so the narrower constraint can be re-created.
    op.execute("UPDATE jobs SET status = 'failed' WHERE status = 'illustrating'")
    op.drop_constraint(_CONSTRAINT, "jobs", type_="check")
    op.create_check_constraint(_CONSTRAINT, "jobs", f"status IN ({_OLD_STATUSES})")
