"""GOLDEN DB tier for the spend-history SQL (`-m golden`, deselected by
default — never runs in CI). Same throwaway postgres as test_worker_db.py:

    docker run -d --rm --name chefclaw-golden-pg \
        -p 127.0.0.1:55432:5432 \
        -e POSTGRES_HOST_AUTH_METHOD=trust \
        -e POSTGRES_USER=chefclaw -e POSTGRES_DB=chefclaw_golden \
        postgres:18
    cd backend && uv run pytest -m golden -q
    docker stop chefclaw-golden-pg

Proves the per-UTC-day / per-model aggregation buckets correctly across day
boundaries and that the window excludes rows older than the period.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chefclaw.config import Settings
from chefclaw.models import Base, Job, LlmSpend, User
from chefclaw.spend import spend_by_day_and_model, spend_summary

pytestmark = pytest.mark.golden

GOLDEN_DB_URL = "postgresql+asyncpg://chefclaw@127.0.0.1:55432/chefclaw_golden"

# Fixed "now" anchors would drift; everything derives from the real today so
# the windowing assertions stay honest.
TODAY = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


@pytest.fixture
async def engine():
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
    yield engine
    await engine.dispose()


@pytest.fixture
async def sessionmaker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def owner_id(sessionmaker) -> uuid.UUID:
    async with sessionmaker() as session:
        user = User(name="owner")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _seed(sessionmaker, owner_id: uuid.UUID) -> None:
    """One job + ledger rows spread across UTC days and models."""
    async with sessionmaker() as session:
        job = Job(
            owner_id=owner_id,
            type="extract",
            payload={"url": "https://example.test/v", "fetch_url": "https://example.test/v"},
            platform="bilibili",
            canonical_id="BVspend001-p1",
            status="failed",
        )
        session.add(job)
        await session.flush()

        def row(model: str, cost: str, created_at: datetime, tokens_in: int = 100) -> LlmSpend:
            return LlmSpend(
                job_id=job.id,
                owner_id=owner_id,
                model=model,
                tokens_in=tokens_in,
                tokens_out=10,
                tokens_thinking=0,
                cost_usd=Decimal(cost),
                created_at=created_at,
            )

        session.add_all(
            [
                # Two models today (same UTC day bucket, distinct slices).
                row("gemini-2.5-flash", "0.30", TODAY),
                row("gemini-2.5-flash", "0.20", TODAY.replace(hour=1)),
                row("qwen3-vl-plus", "0.10", TODAY),
                # Yesterday 23:59 UTC — must land in yesterday's bucket.
                row("gemini-2.5-flash", "0.05", _days_ago(1).replace(hour=23, minute=59)),
                # Far outside any reasonable window.
                row("gemini-2.5-flash", "9.99", _days_ago(40)),
            ]
        )
        await session.commit()


def _days_ago(days: int) -> datetime:
    from datetime import timedelta

    return TODAY - timedelta(days=days)


async def test_spend_by_day_and_model_buckets_utc_days(sessionmaker, owner_id) -> None:
    await _seed(sessionmaker, owner_id)
    async with sessionmaker() as session:
        rows = await spend_by_day_and_model(session, owner_id, days=30)

    assert [(r.day, r.model) for r in rows] == [
        (TODAY.date(), "gemini-2.5-flash"),
        (TODAY.date(), "qwen3-vl-plus"),
        (_days_ago(1).date(), "gemini-2.5-flash"),
    ]
    today_flash = rows[0]
    assert today_flash.cost_usd == Decimal("0.50")  # 0.30 + 0.20 aggregated
    assert today_flash.attempts == 2
    assert today_flash.tokens_in == 200
    # The 40-day-old row is excluded by the 30-day window (no 9.99 anywhere).
    assert all(r.cost_usd < Decimal("1") for r in rows)


async def test_spend_summary_reads_caps_and_ledger(sessionmaker, owner_id) -> None:
    await _seed(sessionmaker, owner_id)
    settings = Settings(monthly_llm_budget_usd="10", max_extraction_attempts_per_day="25")
    async with sessionmaker() as session:
        summary = await spend_summary(session, settings, owner_id, days=30)

    assert summary.budget_monthly_usd == Decimal("10")
    assert summary.daily_attempt_cap == 25
    assert summary.attempts_today == 3  # the three TODAY rows
    assert summary.period_days == 30
    # Month-to-date depends on where in the month "today" falls — it must at
    # least include today's three rows and never the 40-day-old one.
    assert Decimal("0.60") <= summary.month_to_date_usd < Decimal("9")


async def test_spend_summary_failclosed_caps_are_none(sessionmaker, owner_id) -> None:
    async with sessionmaker() as session:
        summary = await spend_summary(session, Settings(), owner_id, days=7)
    assert summary.budget_monthly_usd is None
    assert summary.daily_attempt_cap is None
    assert summary.rows == []
