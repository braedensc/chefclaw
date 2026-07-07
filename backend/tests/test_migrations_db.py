"""GOLDEN migration tier (`-m golden`, deselected by default — never runs in CI).

Applies the REAL Alembic chain against a THROWAWAY postgres and asserts the M2
identity migration's backfill (`d1e2f3a4b5c6`) and the owner-scope dedupe
constraint swap (`e2f3a4b5c6d7`) — the one thing create_all can't prove: that
the migration transforms an EXISTING single-owner database correctly.

Uses a DEDICATED database (`chefclaw_migrations_check`) so the fresh alembic
chain starts from empty — the shared `chefclaw_golden` DB is create_all'd by the
other golden tests, which would collide with migration #1's create_table. Needs
the same throwaway postgres as test_worker_db.py (127.0.0.1:55432); see that
module's docstring for the docker run command.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.golden

_ADMIN_URL = "postgresql+asyncpg://chefclaw@127.0.0.1:55432/chefclaw_golden"
_MIGRATION_DB = "chefclaw_migrations_check"
_MIGRATION_URL = f"postgresql+asyncpg://chefclaw@127.0.0.1:55432/{_MIGRATION_DB}"
_BACKEND_DIR = Path(__file__).resolve().parents[1]


async def _admin_exec(sql: str) -> None:
    engine = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


@pytest.fixture
async def migrated_db():
    # Fresh dedicated DB so the alembic chain starts from empty.
    try:
        await _admin_exec(f'DROP DATABASE IF EXISTS "{_MIGRATION_DB}" WITH (FORCE)')
        await _admin_exec(f'CREATE DATABASE "{_MIGRATION_DB}"')
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(
            f"throwaway postgres not reachable on 127.0.0.1:55432 ({exc}) — "
            "see tests/test_worker_db.py for the docker run command"
        )
    # Run the REAL alembic CLI in a subprocess (faithful; sidesteps the nested
    # event loop of alembic's async env.py). env points it at the dedicated DB.
    env = {
        **os.environ,
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "55432",
        "DB_USER": "chefclaw",
        "DB_PASSWORD": "",
        "DB_NAME": _MIGRATION_DB,
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr}"
    engine = create_async_engine(_MIGRATION_URL)
    try:
        yield engine
    finally:
        await engine.dispose()
        await _admin_exec(f'DROP DATABASE IF EXISTS "{_MIGRATION_DB}" WITH (FORCE)')


async def test_m2_migration_backfills_owner_and_swaps_dedupe(migrated_db) -> None:
    """The migrated schema (from migration #1's seed owner through the M2 chain):
    the seed owner became a real admin identity, the recipe dedupe constraint is
    the owner-scoped one, and the invites/sessions tables landed."""
    async with migrated_db.connect() as conn:
        owner = (
            await conn.execute(
                text("SELECT name, email, is_admin, display_name, status FROM users")
            )
        ).all()
        assert owner == [("owner", "owner@localhost", True, "owner", "active")]

        uniques = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'recipes'::regclass AND contype = 'u'"
                    )
                )
            ).all()
        }
        assert uniques == {"uq_recipes_owner_platform_canonical_dish"}

        tables = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE tablename IN ('invites', 'sessions', 'request_events')"
                    )
                )
            ).all()
        }
        # request_events lands with the V2-D rate-limit revision (f3a4b5c6d7e8).
        assert tables == {"invites", "sessions", "request_events"}


async def test_m2_owner_scoped_unique_allows_two_owners_same_canonical(migrated_db) -> None:
    """Against the MIGRATED schema: two owners hold the SAME (platform,
    canonical_id, dish_index) with no conflict — the swap's whole point. The
    pre-M2 3-column constraint would have rejected the second insert."""
    async with migrated_db.begin() as conn:
        owner_a = (
            await conn.execute(
                text("INSERT INTO users (name, email) VALUES ('a', 'a@x') RETURNING id")
            )
        ).scalar_one()
        owner_b = (
            await conn.execute(
                text("INSERT INTO users (name, email) VALUES ('b', 'b@x') RETURNING id")
            )
        ).scalar_one()
        for owner in (owner_a, owner_b):
            await conn.execute(
                text(
                    "INSERT INTO recipes "
                    "(owner_id, platform, source_url, canonical_id, dish_index, document) "
                    "VALUES (:o, 'bilibili', 'u', 'BVx', 0, '{}'::jsonb)"
                ),
                {"o": owner},
            )
    async with migrated_db.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM recipes"))).scalar_one()
    assert count == 2  # both rows coexist under the owner-scoped UNIQUE
