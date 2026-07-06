"""GOLDEN DB tier (`-m golden`, deselected by default — never runs in CI).

Exercises what the fakes cannot: the real FOR UPDATE SKIP LOCKED claim, the
real one-transaction atomic store, the real IntegrityError→adopt path, and
kill-mid-job semantics — against a THROWAWAY postgres, NEVER the compose DB
(kit inversion: local compose volumes are production).

Start the throwaway instance first (unique name, non-default port, trust
auth, auto-removed on stop):

    docker run -d --rm --name chefclaw-golden-pg \
        -p 127.0.0.1:55432:5432 \
        -e POSTGRES_HOST_AUTH_METHOD=trust \
        -e POSTGRES_USER=chefclaw -e POSTGRES_DB=chefclaw_golden \
        postgres:18-alpine
    cd backend && uv run pytest -m golden -q
    docker stop chefclaw-golden-pg

Each test runs in its own schema-per-run database state: tables are dropped
and recreated per test for isolation.
"""

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chefclaw.config import Settings
from chefclaw.extractors.fake import FakeExtractor, default_dish
from chefclaw.models import Base, Job, LlmSpend, Recipe, User
from chefclaw.services.jobs import Worker, enqueue_extract
from chefclaw.services.repo import PostgresJobStore
from chefclaw.sources.fake import FakeSource

pytestmark = pytest.mark.golden

# The throwaway instance — NON-default port so a fat-fingered default can
# never reach the real compose postgres (which listens on 5432).
GOLDEN_DB_URL = "postgresql+asyncpg://chefclaw@127.0.0.1:55432/chefclaw_golden"
FAKE_URL = "https://fake.example/video/1"


async def _noop_sleep(_seconds: float) -> None:
    return None


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


def golden_settings(tmp_path: Path) -> Settings:
    return Settings(
        chefclaw_api_token="golden-test",
        monthly_llm_budget_usd="10",
        max_extraction_attempts_per_day="25",
        chefclaw_extractor="fake",
        media_retention="discard",
        scratch_dir=str(tmp_path / "scratch"),
        media_dir=str(tmp_path / "media"),
    )


def make_store(sessionmaker, tmp_path: Path) -> PostgresJobStore:
    return PostgresJobStore(sessionmaker, golden_settings(tmp_path))


async def test_skip_locked_claim_is_exclusive(sessionmaker, owner_id, tmp_path: Path) -> None:
    """Two concurrent claimers must never grab the same row; oldest first."""
    store = make_store(sessionmaker, tmp_path)
    source = FakeSource(platform="bilibili", canonical_id="BVgolden001-p1")
    settings = golden_settings(tmp_path)
    job_a, _ = await enqueue_extract(store, owner_id, FAKE_URL, [source], settings)
    source2 = FakeSource(platform="bilibili", canonical_id="BVgolden002-p1")
    job_b, _ = await enqueue_extract(
        store, owner_id, "https://fake.example/video/2", [source2], settings
    )

    claimed = await asyncio.gather(store.claim_next_job(), store.claim_next_job())
    claimed_ids = {job.id for job in claimed if job is not None}
    assert claimed_ids == {job_a.id, job_b.id}  # both claimed, no double-claim
    for job in claimed:
        assert job.status == "downloading"
        assert job.attempts == 1
    assert await store.claim_next_job() is None  # queue drained


async def test_atomic_store_and_ledger(sessionmaker, owner_id, tmp_path: Path) -> None:
    """Full pipeline against real SQL: N-row insert + job flip in one
    transaction, spend ledgered, dedupe visible to a re-enqueue."""
    store = make_store(sessionmaker, tmp_path)
    settings = golden_settings(tmp_path)
    source = FakeSource(platform="bilibili", canonical_id="BVgolden003-p1")
    dish_two = default_dish()
    dish_two["dish_name"] = {"en": "Second dish", "original": "第二道菜"}
    extractor = FakeExtractor(dishes=[default_dish(), dish_two])
    worker = Worker(
        store=store,
        adapters=[source],
        settings=settings,
        extractor_factory=lambda _s: extractor,
        sleeper=_noop_sleep,
    )

    await enqueue_extract(store, owner_id, FAKE_URL, [source], settings)
    job = await store.claim_next_job()
    await worker.process(job)

    async with sessionmaker() as session:
        stored_job = await session.get(Job, job.id)
        recipes = (
            (await session.execute(select(Recipe).order_by(Recipe.dish_index))).scalars().all()
        )
        spend_count = await session.scalar(select(func.count(LlmSpend.id)))
    assert stored_job.status == "stored"
    assert len(recipes) == 2
    assert [r.dish_index for r in recipes] == [0, 1]
    assert stored_job.result_recipe_ids == [r.id for r in recipes]
    assert recipes[0].document["source"]["url"] == FAKE_URL
    assert spend_count == 1

    # Re-enqueueing the same canonical identity returns the completed job:
    again, existing = await enqueue_extract(store, owner_id, FAKE_URL, [source], settings)
    assert existing is True
    assert again.id == job.id


async def test_store_results_unique_violation_adopts(
    sessionmaker, owner_id, tmp_path: Path
) -> None:
    """The real UNIQUE(platform, canonical_id, dish_index) fires → None →
    the caller adopts the racer's rows instead of failing."""
    store = make_store(sessionmaker, tmp_path)
    settings = golden_settings(tmp_path)
    source = FakeSource(platform="bilibili", canonical_id="BVgolden004-p1")
    extractor = FakeExtractor()
    worker = Worker(
        store=store,
        adapters=[source],
        settings=settings,
        extractor_factory=lambda _s: extractor,
        sleeper=_noop_sleep,
    )

    # Job A stores first (the "racer").
    job_a, _ = await enqueue_extract(store, owner_id, FAKE_URL, [source], settings)
    claimed_a = await store.claim_next_job()
    await worker.process(claimed_a)
    raced_ids = await store.find_recipe_ids("bilibili", "BVgolden004-p1")
    assert raced_ids

    # Job B for the same canonical identity hits the constraint directly.
    async with sessionmaker() as session:
        job_b = Job(
            owner_id=owner_id,
            type="extract",
            payload={"url": FAKE_URL, "fetch_url": FAKE_URL},
            platform="bilibili",
            canonical_id="BVgolden004-p1",
            status="validating",
        )
        session.add(job_b)
        await session.commit()
        await session.refresh(job_b)

    from chefclaw.documents import SourceInfo, validate_extraction

    documents = validate_extraction(
        [default_dish()],
        SourceInfo(platform="bilibili", url=FAKE_URL, creator=None, video_duration_seconds=None),
    )
    result = await store.store_results(job_b, documents, extraction_meta={})
    assert result is None  # the real IntegrityError path
    await store.adopt_recipes(job_b.id, raced_ids)
    async with sessionmaker() as session:
        adopted = await session.get(Job, job_b.id)
        recipe_count = await session.scalar(select(func.count(Recipe.id)))
    assert adopted.status == "stored"
    assert adopted.result_recipe_ids == raced_ids
    assert recipe_count == len(raced_ids)  # no duplicate rows leaked


async def test_hard_delete_reopens_extraction(sessionmaker, owner_id, tmp_path: Path) -> None:
    """CLAUDE.md hard-delete semantics against REAL SQL: while recipes exist
    the stored job dedupes; once they are hard-deleted the same canonical id
    must re-extract (new job, new paid call, fresh rows — no UNIQUE conflict,
    no dedupe hit pointing at recipes that are gone)."""
    store = make_store(sessionmaker, tmp_path)
    settings = golden_settings(tmp_path)
    source = FakeSource(platform="bilibili", canonical_id="BVgolden006-p1")
    extractor = FakeExtractor()
    worker = Worker(
        store=store,
        adapters=[source],
        settings=settings,
        extractor_factory=lambda _s: extractor,
        sleeper=_noop_sleep,
    )

    job, _ = await enqueue_extract(store, owner_id, FAKE_URL, [source], settings)
    await worker.process(await store.claim_next_job())

    # While recipes exist, the stored job dedupes:
    again, existing = await enqueue_extract(store, owner_id, FAKE_URL, [source], settings)
    assert existing is True
    assert again.id == job.id

    # HARD delete every recipe (the MVP DELETE /api/recipes/{id} semantics):
    async with sessionmaker() as session:
        for recipe in (await session.execute(select(Recipe))).scalars().all():
            await session.delete(recipe)
        await session.commit()

    # The same canonical id now re-opens extraction — never a dedupe hit
    # whose recipes are gone:
    fresh, existing = await enqueue_extract(store, owner_id, FAKE_URL, [source], settings)
    assert existing is False
    assert fresh.id != job.id
    assert fresh.status == "pending"

    await worker.process(await store.claim_next_job())
    async with sessionmaker() as session:
        stored_fresh = await session.get(Job, fresh.id)
        recipe_count = await session.scalar(select(func.count(Recipe.id)))
    assert stored_fresh.status == "stored"
    assert recipe_count == 1  # fresh rows inserted, no UNIQUE conflict
    assert len(stored_fresh.result_recipe_ids) == 1
    assert len(extractor.calls) == 2  # the re-extract really re-ran the model


async def test_kill_mid_extract_no_double_spend_and_reconcile(
    sessionmaker, owner_id, tmp_path: Path
) -> None:
    """Cancel the worker task mid-extract (docker compose watch flavor):
    no spend row lands, the job stays in its running stage, reconcile flips
    it to interrupted, and a restarted worker never auto-reruns it."""

    class BlockingExtractor:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.calls = 0

        async def extract(self, video_path, source_title, source_duration_seconds):
            self.calls += 1
            self.started.set()
            await asyncio.Event().wait()

    store = make_store(sessionmaker, tmp_path)
    settings = golden_settings(tmp_path)
    source = FakeSource(platform="bilibili", canonical_id="BVgolden005-p1")
    blocking = BlockingExtractor()
    worker = Worker(
        store=store,
        adapters=[source],
        settings=settings,
        extractor_factory=lambda _s: blocking,
        sleeper=_noop_sleep,
    )

    job, _ = await enqueue_extract(store, owner_id, FAKE_URL, [source], settings)
    task = asyncio.create_task(worker.run_forever())
    await asyncio.wait_for(blocking.started.wait(), timeout=15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with sessionmaker() as session:
        killed = await session.get(Job, job.id)
        spend_count = await session.scalar(select(func.count(LlmSpend.id)))
    assert killed.status == "extracting"  # left mid-stage on purpose
    assert spend_count == 0  # the attempt never completed — nothing ledgered

    # "Restart": a fresh worker reconciles on startup, then idles — the
    # interrupted job is terminal and must NOT be re-claimed or re-spent.
    fresh_extractor = FakeExtractor()
    restarted = Worker(
        store=store,
        adapters=[source],
        settings=settings,
        extractor_factory=lambda _s: fresh_extractor,
        sleeper=_noop_sleep,
    )
    restart_task = asyncio.create_task(restarted.run_forever())
    await asyncio.sleep(1.0)  # a few idle loops
    restart_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await restart_task

    async with sessionmaker() as session:
        reconciled = await session.get(Job, job.id)
        spend_count = await session.scalar(select(func.count(LlmSpend.id)))
    assert reconciled.status == "failed"
    assert reconciled.error_type == "interrupted"
    assert spend_count == 0  # NO double spend, NO auto-rerun of paid work
    assert fresh_extractor.calls == []
