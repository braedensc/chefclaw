"""Request throttle (chefclaw.ratelimit).

Unit tier: the middleware's bucket selection + 429 behavior, driven by a FAKE
in-memory limiter injected onto ``app.state`` (create_app adds the middleware;
the real limiter is wired in the lifespan, which ASGITransport never runs). The
golden tier drives the REAL PostgresRateLimiter against a throwaway PG.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chefclaw.models import Base, RequestEvent
from chefclaw.ratelimit import PostgresRateLimiter, RateLimitRule
from tests.conftest import make_app


class _FakeLimiter:
    """In-memory stand-in with the PostgresRateLimiter interface."""

    def __init__(self, *, authenticated_limit: int, public_limit: int) -> None:
        self.authenticated_rule = RateLimitRule(limit=authenticated_limit, window_seconds=60)
        self.public_rule = RateLimitRule(limit=public_limit, window_seconds=60)
        self._counts: dict[str, int] = {}

    async def check_and_record(self, key, rule, *, now=None) -> bool:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key] <= rule.limit


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── middleware (unit) ─────────────────────────────────────────────────────────


async def test_public_bucket_throttles_after_limit() -> None:
    app = make_app()
    app.state.rate_limiter = _FakeLimiter(authenticated_limit=100, public_limit=2)
    async with _client(app) as c:
        r1 = await c.get("/api/me")  # no cookie ⇒ public bucket
        r2 = await c.get("/api/me")
        r3 = await c.get("/api/me")
    assert (r1.status_code, r2.status_code) == (200, 200)
    assert r3.status_code == 429
    assert r3.json()["error_type"] == "rate_limited"
    assert r3.headers["retry-after"] == "60"


async def test_session_cookie_selects_authenticated_bucket() -> None:
    app = make_app()
    # authenticated bucket is generous (5), public bucket is strict (1).
    app.state.rate_limiter = _FakeLimiter(authenticated_limit=5, public_limit=1)
    cookie = {"Cookie": "chefclaw_session=abc"}
    async with _client(app) as c:
        # WITH a cookie ⇒ authenticated bucket: a 2nd request is still fine.
        a1 = await c.get("/api/me", headers=cookie)
        a2 = await c.get("/api/me", headers=cookie)
        # WITHOUT a cookie ⇒ public bucket (limit 1): the 2nd is throttled.
        p1 = await c.get("/api/me")
        p2 = await c.get("/api/me")
    assert (a1.status_code, a2.status_code) == (200, 200)
    assert p1.status_code == 200
    assert p2.status_code == 429


async def test_zero_limit_disables_bucket() -> None:
    app = make_app()
    app.state.rate_limiter = _FakeLimiter(authenticated_limit=100, public_limit=0)
    async with _client(app) as c:
        for _ in range(5):  # public bucket disabled ⇒ never throttled
            assert (await c.get("/api/me")).status_code == 200


async def test_no_limiter_means_no_throttle() -> None:
    app = make_app()  # nothing set on app.state.rate_limiter (the unit-tier default)
    async with _client(app) as c:
        for _ in range(5):
            assert (await c.get("/api/me")).status_code == 200


# ── PostgresRateLimiter (golden — real SQL) ───────────────────────────────────

GOLDEN_DB_URL = "postgresql+asyncpg://chefclaw@127.0.0.1:55432/chefclaw_golden"


@pytest.fixture
async def golden_sm():
    engine = create_async_engine(GOLDEN_DB_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment guard
        await engine.dispose()
        pytest.skip(f"throwaway postgres not reachable on 127.0.0.1:55432 ({exc})")
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.golden
async def test_postgres_limiter_window_independence_and_prune(golden_sm) -> None:
    rule = RateLimitRule(limit=2, window_seconds=60)
    limiter = PostgresRateLimiter(golden_sm, authenticated_rule=rule, public_rule=rule)

    assert await limiter.check_and_record("k1", rule) is True
    assert await limiter.check_and_record("k1", rule) is True
    assert await limiter.check_and_record("k1", rule) is False  # over the trailing-window cap
    # A different key has its own independent budget.
    assert await limiter.check_and_record("k2", rule) is True

    # The window slides: 120 s later, k1's earlier events fall outside the 60 s
    # window, so it is allowed again — and the opportunistic prune has dropped the
    # now-stale rows, bounding the table.
    future = datetime.now(UTC) + timedelta(seconds=120)
    assert await limiter.check_and_record("k1", rule, now=future) is True
    async with golden_sm() as s:
        k1_rows = await s.scalar(
            select(func.count()).select_from(RequestEvent).where(RequestEvent.key == "k1")
        )
    assert k1_rows == 1  # only the fresh event survives the prune
