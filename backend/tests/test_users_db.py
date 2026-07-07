"""GOLDEN DB tier for M3 per-user caps (`-m golden`, deselected by default —
never runs in CI). Proves the real users-column SQL against a throwaway
postgres: ``set_user_budget`` round-trip + quantization, ``read_user_caps``,
and the load-bearing property — ``check_budget`` gates two users with different
per-user caps INDEPENDENTLY against a real ledger, and NULL columns fall back to
the global env cap. Same throwaway PG as test_worker_db.py:

    docker run -d --rm --name chefclaw-golden-pg \
        -p 127.0.0.1:55432:5432 \
        -e POSTGRES_HOST_AUTH_METHOD=trust \
        -e POSTGRES_USER=chefclaw -e POSTGRES_DB=chefclaw_golden \
        postgres:18
    cd backend && uv run pytest -m golden -q
    docker stop chefclaw-golden-pg
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chefclaw import spend
from chefclaw.config import Settings
from chefclaw.errors import BudgetExceededError
from chefclaw.models import Base, Job, LlmSpend, User
from chefclaw.services import users

pytestmark = pytest.mark.golden

GOLDEN_DB_URL = "postgresql+asyncpg://chefclaw@127.0.0.1:55432/chefclaw_golden"


def _settings() -> Settings:
    return Settings(monthly_llm_budget_usd="10", max_extraction_attempts_per_day="25")


@pytest.fixture
async def sm():
    engine = create_async_engine(GOLDEN_DB_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment guard
        await engine.dispose()
        pytest.skip(
            f"throwaway postgres not reachable on 127.0.0.1:55432 ({exc}) — "
            "see the module docstring for the docker run command"
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _add_user(
    sm, *, email: str, monthly: Decimal | None = None, daily: int | None = None
) -> uuid.UUID:
    async with sm() as s:
        user = User(
            name=email, email=email, monthly_budget_usd=monthly, max_attempts_per_day=daily
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user.id


async def _ledger(sm, owner_id: uuid.UUID, *, cost: str, rows: int = 1) -> None:
    """Add ``rows`` ledger rows (default created_at = now ⇒ this month/today)."""
    async with sm() as s:
        job = Job(
            owner_id=owner_id,
            type="extract",
            payload={"url": "https://example.test/v", "fetch_url": "https://example.test/v"},
            platform="bilibili",
            canonical_id=f"c-{uuid.uuid4()}",
            status="failed",
        )
        s.add(job)
        await s.flush()
        for _ in range(rows):
            s.add(
                LlmSpend(
                    job_id=job.id,
                    owner_id=owner_id,
                    model="gemini-2.5-flash",
                    cost_usd=Decimal(cost),
                )
            )
        await s.commit()


# ── set_user_budget round-trip ───────────────────────────────────────────────


async def test_set_user_budget_round_trips_through_read_user_caps(sm) -> None:
    uid = await _add_user(sm, email="a@x.com")
    row = await users.set_user_budget(
        sm, uid, values={"monthly_budget_usd": 7.5, "max_attempts_per_day": 4}
    )
    assert row is not None
    assert row.monthly_budget_usd == Decimal("7.50")  # quantized to the cent
    assert row.max_attempts_per_day == 4

    async with sm() as s:
        caps = await spend.read_user_caps(s, uid)
    assert caps == (Decimal("7.50"), 4)


async def test_set_user_budget_partial_and_clear(sm) -> None:
    uid = await _add_user(sm, email="b@x.com", monthly=Decimal("5.00"), daily=9)
    # Partial: only daily changes; monthly is left untouched.
    await users.set_user_budget(sm, uid, values={"max_attempts_per_day": 3})
    async with sm() as s:
        assert await spend.read_user_caps(s, uid) == (Decimal("5.00"), 3)
    # Explicit null clears monthly back to the global default (column NULL).
    await users.set_user_budget(sm, uid, values={"monthly_budget_usd": None})
    async with sm() as s:
        assert await spend.read_user_caps(s, uid) == (None, 3)


async def test_set_user_budget_missing_user_is_none(sm) -> None:
    assert await users.set_user_budget(sm, uuid.uuid4(), values={"max_attempts_per_day": 1}) is None


async def test_read_user_caps_no_row(sm) -> None:
    async with sm() as s:
        assert await spend.read_user_caps(s, uuid.uuid4()) == (None, None)


# ── the load-bearing property: independent gating ────────────────────────────


async def test_two_users_different_caps_gated_independently(sm) -> None:
    """Global budget $10. User LOW is capped at $1, user HIGH at $100. Each has
    spent $2 — LOW is over its own cap, HIGH is well under its own. The gate
    reads each user's real column + real owner-scoped ledger."""
    low = await _add_user(sm, email="low@x.com", monthly=Decimal("1.00"))
    high = await _add_user(sm, email="high@x.com", monthly=Decimal("100.00"))
    await _ledger(sm, low, cost="2.00")
    await _ledger(sm, high, cost="2.00")

    async with sm() as s:
        with pytest.raises(BudgetExceededError, match="per-user cap"):
            await spend.check_budget(s, _settings(), low)
    async with sm() as s:
        await spend.check_budget(s, _settings(), high)  # under its own $100 cap


async def test_null_columns_fall_back_to_global(sm) -> None:
    """A user with NULL cap columns is gated by the global env cap ($10): $2
    spent passes; topping past $10 blocks with the ENV-VAR source in the message."""
    uid = await _add_user(sm, email="null@x.com")  # both columns NULL
    await _ledger(sm, uid, cost="2.00")
    async with sm() as s:
        await spend.check_budget(s, _settings(), uid)  # under global

    await _ledger(sm, uid, cost="9.00")  # now $11 month-to-date
    async with sm() as s:
        with pytest.raises(BudgetExceededError, match="MONTHLY_LLM_BUDGET_USD"):
            await spend.check_budget(s, _settings(), uid)


async def test_per_user_daily_cap_gates_independently(sm) -> None:
    """A per-user daily cap (2) below the global (25) blocks after 2 cheap
    attempts today, without tripping the monthly budget."""
    uid = await _add_user(sm, email="daily@x.com", daily=2)
    await _ledger(sm, uid, cost="0.01", rows=2)
    async with sm() as s:
        with pytest.raises(BudgetExceededError, match="per-user cap"):
            await spend.check_budget(s, _settings(), uid)


# ── paid tier round-trip ─────────────────────────────────────────────────────


async def test_paid_tier_defaults_false_and_reads_back(sm) -> None:
    uid = await _add_user(sm, email="tier@x.com")
    async with sm() as s:
        assert await users.read_paid_tier(s, uid) is False  # column default
        assert await users.read_paid_tier(s, uuid.uuid4()) is False  # no row


async def test_set_paid_tier_round_trips(sm) -> None:
    uid = await _add_user(sm, email="pro@x.com")
    row = await users.set_user_budget(sm, uid, values={"paid_tier": True})
    assert row is not None and row.paid_tier is True
    async with sm() as s:
        assert await users.read_paid_tier(s, uid) is True
    # Flip it back off; caps set in the same call are independent.
    await users.set_user_budget(sm, uid, values={"paid_tier": False, "max_attempts_per_day": 5})
    async with sm() as s:
        assert await users.read_paid_tier(s, uid) is False
        assert await spend.read_user_caps(s, uid) == (None, 5)
