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
from typing import Any, NamedTuple, Protocol

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chefclaw import spend
from chefclaw.config import Settings
from chefclaw.documents import EstimatedAttributes, RecipeDocument
from chefclaw.extractors import ExtractionUsage
from chefclaw.models import Job, JobStatus, Recipe

__all__ = [
    "ACTIVE_STATUSES",
    "RUNNING_STATUSES",
    "JobStore",
    "PostgresJobStore",
    "PostgresSpendReader",
    "RecipeImageRef",
    "SpendReader",
]


class RecipeImageRef(NamedTuple):
    """The slice of a recipe the illustration backfill needs — deliberately
    not the full ORM row (extraction_meta JSONB would ride along for nothing).
    Carries the ``document`` (the prompt is built from its text fields),
    ``owner_id`` + ``job_id`` (to budget-gate + attribute the spend row), and
    the media-path parts."""

    id: uuid.UUID
    owner_id: uuid.UUID
    job_id: uuid.UUID
    platform: str
    canonical_id: str
    dish_index: int
    document: dict[str, Any]

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

    async def list_jobs(self, owner_id: uuid.UUID, limit: int = 20) -> list[Job]: ...

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
        estimates: list[EstimatedAttributes | None],
        *,
        extraction_meta: dict[str, Any],
    ) -> list[uuid.UUID] | None: ...

    async def list_recipes_missing_images(self) -> list[RecipeImageRef]: ...

    async def set_recipe_image(
        self, recipe_id: uuid.UUID, image_url: str, style_version: str
    ) -> None: ...

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

    async def list_jobs(self, owner_id: uuid.UUID, limit: int = 20) -> list[Job]:
        """The jobs drawer (active + recent): this owner's jobs, newest
        activity first (updated_at moves on every status change)."""
        stmt = (
            select(Job)
            .where(Job.owner_id == owner_id)
            .order_by(Job.updated_at.desc())
            .limit(limit)
        )
        async with self._sessionmaker() as session:
            return list((await session.execute(stmt)).scalars().all())

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
        estimates: list[EstimatedAttributes | None],
        *,
        extraction_meta: dict[str, Any],
    ) -> list[uuid.UUID] | None:
        """ATOMIC multi-dish store: N recipe inserts + the job's flip to
        ``stored`` in ONE transaction (§16.4). ``image_url`` lands NULL here —
        illustrations are generated best-effort AFTER this commit (never inside
        the paid-work crash-loss window) and persisted via set_recipe_image.
        Derived ``estimated`` attributes (spiciness/difficulty — kept SEPARATE
        from the verbatim document, Hard Rule 7) are stored atomically here.
        Returns the new recipe ids, or ``None`` when UNIQUE(platform,
        canonical_id, dish_index) fired — a raced duplicate the caller adopts
        instead of failing."""
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
                            estimated=(
                                estimate.model_dump(mode="json")
                                if estimate is not None
                                else None
                            ),
                            extraction_meta=extraction_meta,
                        )
                        for index, (document, estimate) in enumerate(
                            zip(documents, estimates, strict=False)
                        )
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

    async def list_recipes_missing_images(self) -> list[RecipeImageRef]:
        """Startup illustration-backfill input: recipes WHERE image_url IS NULL,
        joined to their originating stored job (which carries the recipe id in
        result_recipe_ids) so the backfill can attribute its spend row to a real
        jobs row. The document rides along (the prompt is built from its text
        fields); extraction_meta stays unloaded. A recipe with no locatable job
        is skipped (an inner join) — the illustration budget row needs a valid
        FK."""
        stmt = (
            select(
                Recipe.id,
                Recipe.owner_id,
                Job.id.label("job_id"),
                Recipe.platform,
                Recipe.canonical_id,
                Recipe.dish_index,
                Recipe.document,
            )
            .join(Job, Job.result_recipe_ids.any(Recipe.id))
            .where(Recipe.image_url.is_(None))
            .order_by(Recipe.created_at)
        )
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
        return [RecipeImageRef(*row) for row in rows]

    async def set_recipe_image(
        self, recipe_id: uuid.UUID, image_url: str, style_version: str
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(Recipe)
                .where(Recipe.id == recipe_id)
                .values(image_url=image_url, image_style_version=style_version)
            )

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
            # After the committed write: 80%/100% crossing-edge budget alerts
            # (best-effort — alert_budget_progress never raises; V2-A ADR).
            await spend.alert_budget_progress(session, self._settings, owner_id, cost_usd)


class SpendReader(Protocol):
    """What the spend endpoint needs — kept beside JobStore for the same
    reason: the CI unit tier fakes it (no database), the golden tier runs it."""

    async def summary(self, owner_id: uuid.UUID, *, days: int) -> spend.SpendSummary: ...


class PostgresSpendReader:
    """Real ledger reads for GET /api/spend."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    async def summary(self, owner_id: uuid.UUID, *, days: int) -> spend.SpendSummary:
        async with self._sessionmaker() as session:
            return await spend.spend_summary(session, self._settings, owner_id, days=days)
