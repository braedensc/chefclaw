"""GOLDEN-SUITE ONLY (compose.golden.yaml): ensure a user row exists with the
configured ``CHEFCLAW_FAKE_OWNER_ID`` so FAKE auth resolves a REAL,
recipe-owning admin.

Under M2 the golden stack runs in fake auth mode: ``require_owner`` short-circuits
to ``chefclaw_fake_owner_id`` (no cookie/session), and jobs/recipes are stored
under that id. That id must therefore be a real ``users`` row (FK target + the
``/api/me`` lookup). The migration seeds an owner with a random uuidv7, so this
script inserts the FIXED-id admin the fake owner resolves to.

NEVER run this against production — it inserts a fixed-id admin account.
"""

import asyncio

from sqlalchemy import text

from chefclaw import db
from chefclaw.config import get_settings


async def _main() -> None:
    fixed = get_settings().chefclaw_fake_owner_id
    async with db.get_sessionmaker()() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO users (id, name, email, is_admin, status) "
                "VALUES (CAST(:id AS uuid), 'golden-owner', 'golden@localhost', true, 'active') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": fixed},
        )


if __name__ == "__main__":
    asyncio.run(_main())
