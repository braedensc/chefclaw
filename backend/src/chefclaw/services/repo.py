"""The persistence seam the job worker talks through.

Why a seam: the CI test tier runs with NO database (models use JSONB/ARRAY/
uuidv7 — postgres-only), so worker logic is written against this small
:class:`JobStore` protocol. CI tests fake it (``tests/fakes.py``); the golden
DB tier (``tests/test_worker_db.py``, ``-m golden``) exercises the real
:class:`PostgresJobStore` against a throwaway postgres.

Every method opens its own short-lived session/transaction — the strictly
serial worker must never hold a lock across a slow stage (download/extract);
row locks live only inside the claim and the atomic store.
"""

import uuid
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chefclaw import spend
from chefclaw.config import Settings
from chefclaw.documents import RecipeDocument
from chefclaw.extractors import ExtractionUsage
from chefclaw.models import Job, JobStatus, Recipe

__all__ = ["ACTIVE_STATUSES", "RUNNING_STATUSES", "JobStore", "PostgresJobStore"]

# A job in any of these states already owns its (platform, canonical_id) —
# the dedupe check returns it instead of enqueueing a twin.
ACTIVE_STATUSES: tuple[str, ...] = (
    JobStatus.PENDING.value,
    JobStatus.DOWNLOADING.value,
    JobStatus.EXTRACTING.value,
    JobStatus.VALIDATING.value,
)
# Mid-flight states a restart strands — startup reconcile flips these to
# failed/interrupted (explicit human retry only; never auto-rerun paid work).
RUNNING_STATUSES: tuple[str, ...] = (
    JobStatus.DOWNLOADING.value,
    JobStatus.EXTRACTING.value,
    JobStatus.VALIDATING.value,
)

# The §4 claim: one pending job, oldest first, skipping rows another claimer
# holds. attempts increments AT claim (attempts count claims, not successes).
_CLAIM_SQL = text(
    """
    UPDATE jobs
       SET status = 'downloading', attempts = attempts + 1, updated_at = now()
     WHERE id = (
             SELECT id FROM jobs
              WHERE status = 'pending'
              ORDER BY created_at
              LIMIT 1
                FOR UPDATE SKIP LOCKED
           )
    RETURNING id
    """
)


class JobStore(Protocol):
    """What the worker and the enqueue path need from persistence."""

    async def find_active_job(self, platform: str, canonical_id: str) -> Job | None: ...

    async def find_completed_job_with_recipes(
        self, platform: str, canonical_id: str
    ) -> Job | None: ...

    async def insert_job(
        self,
        *,
        owner_id: uuid.UUID,
        job_type: str,
        payload: dict[str, Any],
        platform: str,
        canonical_id: str,
    ) -> Job: ...

    async def get_job(self, job_id: uuid.UUID, owner_id: uuid.UUID) -> Job | None: ...

    async def claim_next_job(self) -> Job | None: ...

    async def set_status(self, job_id: uuid.UUID, status: str) -> None: ...

    async def requeue(self, job_id: uuid.UUID) -> None: ...

    async def mark_failed(self, job_id: uuid.UUID, error_type: str, error_detail: str) -> None: ...

    async def find_recipe_ids(self, platform: str, canonical_id: str) -> list[uuid.UUID]: ...

    async def adopt_recipes(self, job_id: uuid.UUID, recipe_ids: list[uuid.UUID]) -> None: ...

    async def store_results(
        self,
        job: Job,
        documents: list[RecipeDocument],
        *,
        extraction_meta: dict[str, Any],
    ) -> list[uuid.UUID] | None: ...

    async def reconcile_interrupted(self) -> int: ...

    async def check_budget(self, owner_id: uuid.UUID) -> None: ...

    async def record_spend(
        self,
        *,
        job_id: uuid.UUID,
        owner_id: uuid.UUID,
        usage: ExtractionUsage,
        cost_usd: Decimal,
    ) -> None: ...


class PostgresJobStore:
    """The real JobStore over an async sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    # ── dedupe lookups (§16.1: canonical identity, never raw URL) ───────────

    async def find_active_job(self, platform: str, canonical_id: str) -> Job | None:
        stmt = (
            select(Job)
            .where(
                Job.platform == platform,
                Job.canonical_id == canonical_id,
                Job.status.in_(ACTIVE_STATUSES),
            )
            .order_by(Job.created_at)
            .limit(1)
        )
        async with self._sessionmaker() as session:
            return (await session.execute(stmt)).scalars().first()

    async def find_completed_job_with_recipes(
        self, platform: str, canonical_id: str
    ) -> Job | None:
        """The latest stored job for this canonical identity — but only while
        its recipes still exist (hard delete re-opens extraction)."""
        async with self._sessionmaker() as session:
            has_recipes = await session.scalar(
                select(Recipe.id)
                .where(Recipe.platform == platform, Recipe.canonical_id == canonical_id)
                .limit(1)
            )
            if has_recipes is None:
                return None
            stmt = (
                select(Job)
                .where(
                    Job.platform == platform,
                    Job.canonical_id == canonical_id,
                    Job.status == JobStatus.STORED.value,
                )
                .order_by(Job.created_at.desc())
                .limit(1)
            )
            return (await session.execute(stmt)).scalars().first()

    async def insert_job(
        self,
        *,
        owner_id: uuid.UUID,
        job_type: str,
        payload: dict[str, Any],
        platform: str,
        canonical_id: str,
    ) -> Job:
        job = Job(
            owner_id=owner_id,
            type=job_type,
            payload=payload,
            platform=platform,
            canonical_id=canonical_id,
        )
        async with self._sessionmaker() as session:
            session.add(job)
            await session.commit()
            await session.refresh(job)  # load the server defaults (id, timestamps…)
        return job

    async def get_job(self, job_id: uuid.UUID, owner_id: uuid.UUID) -> Job | None:
        stmt = select(Job).where(Job.id == job_id, Job.owner_id == owner_id)
        async with self._sessionmaker() as session:
            return (await session.execute(stmt)).scalars().first()

    # ── worker lifecycle ─────────────────────────────────────────────────────

    async def claim_next_job(self) -> Job | None:
        async with self._sessionmaker() as session:
            async with session.begin():
                row = (await session.execute(_CLAIM_SQL)).first()
                if row is None:
                    return None
                job = await session.get(Job, row[0])
            return job

    async def set_status(self, job_id: uuid.UUID, status: str) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(update(Job).where(Job.id == job_id).values(status=status))

    async def requeue(self, job_id: uuid.UUID) -> None:
        """Retryable failure below the attempt cap: back to pending.
        created_at ordering keeps fairness (older jobs claim first)."""
        await self.set_status(job_id, JobStatus.PENDING.value)

    async def mark_failed(self, job_id: uuid.UUID, error_type: str, error_detail: str) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status=JobStatus.FAILED.value,
                    error_type=error_type,
                    error_detail=error_detail,
                )
            )

    # ── recipes / atomic store (§16.4) ──────────────────────────────────────

    async def find_recipe_ids(self, platform: str, canonical_id: str) -> list[uuid.UUID]:
        stmt = (
            select(Recipe.id)
            .where(Recipe.platform == platform, Recipe.canonical_id == canonical_id)
            .order_by(Recipe.dish_index)
        )
        async with self._sessionmaker() as session:
            return list((await session.execute(stmt)).scalars().all())

    async def adopt_recipes(self, job_id: uuid.UUID, recipe_ids: list[uuid.UUID]) -> None:
        """Point the job at recipes that already exist (idempotent paid stage /
        raced duplicate) and flip it stored — no model call happened."""
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status=JobStatus.STORED.value,
                    result_recipe_ids=recipe_ids,
                    error_type=None,
                    error_detail=None,
                )
            )

    async def store_results(
        self,
        job: Job,
        documents: list[RecipeDocument],
        *,
        extraction_meta: dict[str, Any],
    ) -> list[uuid.UUID] | None:
        """ATOMIC multi-dish store: N recipe inserts + the job's flip to
        ``stored`` in ONE transaction (§16.4). Returns the new recipe ids, or
        ``None`` when UNIQUE(platform, canonical_id, dish_index) fired — a
        raced duplicate the caller adopts instead of failing."""
        source_url = job.payload["url"]
        try:
            async with self._sessionmaker() as session:
                async with session.begin():
                    rows = [
                        Recipe(
                            owner_id=job.owner_id,
                            title_en=document.dish_name.en,
                            title_original=document.dish_name.original,
                            platform=job.platform,
                            source_url=source_url,
                            canonical_id=job.canonical_id,
                            dish_index=index,
                            status="stored",
                            document=document.model_dump(mode="json"),
                            extraction_meta=extraction_meta,
                        )
                        for index, document in enumerate(documents)
                    ]
                    session.add_all(rows)
                    await session.flush()  # RETURNING populates the uuidv7 ids
                    recipe_ids = [row.id for row in rows]
                    await session.execute(
                        update(Job)
                        .where(Job.id == job.id)
                        .values(
                            status=JobStatus.STORED.value,
                            result_recipe_ids=recipe_ids,
                            error_type=None,
                            error_detail=None,
                        )
                    )
            return recipe_ids
        except IntegrityError:
            return None  # raced duplicate — caller adopts the existing rows

    async def reconcile_interrupted(self) -> int:
        """Startup reconcile: any job stranded mid-stage by a restart becomes
        failed/interrupted — explicit human retry only, NEVER auto-rerun paid
        work (docker compose watch restarts the api constantly)."""
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(
                update(Job)
                .where(Job.status.in_(RUNNING_STATUSES))
                .values(
                    status=JobStatus.FAILED.value,
                    error_type="interrupted",
                    error_detail=(
                        "the api restarted while this job was running — "
                        "retry it explicitly (paid work is never auto-rerun)"
                    ),
                )
            )
            return result.rowcount or 0

    # ── spend (delegates to chefclaw.spend with a fresh session) ────────────

    async def check_budget(self, owner_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session:
            await spend.check_budget(session, self._settings, owner_id)

    async def record_spend(
        self,
        *,
        job_id: uuid.UUID,
        owner_id: uuid.UUID,
        usage: ExtractionUsage,
        cost_usd: Decimal,
    ) -> None:
        async with self._sessionmaker() as session:
            await spend.record_spend(
                session, job_id=job_id, owner_id=owner_id, usage=usage, cost_usd=cost_usd
            )
