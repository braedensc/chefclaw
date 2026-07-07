"""LOCAL-DEV seed: make FAKE auth resolve a real, recipe-owning account so the
SPA loads straight to the library with no sign-in step.

Under fake auth (``chefclaw_auth_provider="fake"``, the local/dev default),
``require_owner`` short-circuits to ``chefclaw_fake_owner_id`` WITHOUT reading a
cookie/session (chefclaw.auth). That id must be a real ``users`` row or every
request 404s at ``GET /api/me`` (no account) and recipe inserts fail the owner
FK. The walking-skeleton migration seeds an owner with a RANDOM ``uuidv7()`` id,
so this script inserts the FIXED-id owner the fake provider resolves to — run by
the compose ``migrate`` service right after ``alembic upgrade head``.

Guarded two ways so a REAL deploy never gets a fixed-id admin planted:
- it NO-OPS unless the auth provider is ``fake`` (a ``google`` deploy's accounts
  come from OAuth + the invite gate — never a seed);
- ``ON CONFLICT (id) DO NOTHING`` keeps it idempotent across re-runs.

The email is deliberately distinct from the migration owner's ``owner@localhost``
so the UNIQUE(email) constraint holds; on a fresh dev DB you get two owners and
fake auth uses this one. (Golden has its own ``seed_golden_owner`` with a
golden-specific identity.)
"""

import asyncio

from sqlalchemy import text

from chefclaw import db
from chefclaw.config import get_settings


async def _main() -> None:
    settings = get_settings()
    if settings.chefclaw_auth_provider != "fake":
        # Real accounts come from OAuth + the invite gate; never plant a fixed-id
        # admin on a google deploy (it would collide with the bootstrap-claim's
        # "unclaimed seed admin" lookup).
        print(
            "seed_fake_owner: CHEFCLAW_AUTH_PROVIDER is not 'fake' — skipping "
            "(accounts come from OAuth)."
        )
        return
    fixed = settings.chefclaw_fake_owner_id
    async with db.get_sessionmaker()() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO users (id, name, email, is_admin, status) "
                "VALUES (CAST(:id AS uuid), 'fake-owner', 'fake-owner@localhost', true, 'active') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": fixed},
        )


if __name__ == "__main__":
    asyncio.run(_main())
