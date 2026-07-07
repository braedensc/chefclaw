"""In-memory JobStore fake — the CI-tier stand-in for PostgresJobStore.

The models are postgres-only (JSONB/ARRAY/uuidv7), so the no-database tier
drives the worker through this fake of the :class:`chefclaw.services.repo.
JobStore` seam. ORM instances are used as the data currency (constructing
them needs no database — only executing SQL does), so the worker code paths
are identical in both tiers.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from chefclaw.covers import AssignmentMiss
from chefclaw.documents import EstimatedAttributes, RecipeDocument
from chefclaw.extractors import ExtractionUsage
from chefclaw.models import CoverMiss, Job, Recipe
from chefclaw.services.repo import (
    ACTIVE_STATUSES,
    RUNNING_STATUSES,
    RecipeFrameRef,
    RecipeImageRef,
    RecipeSpriteRef,
)

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class FakeJobStore:
    """Faithful in-memory JobStore.

    Failure injection:
    - ``budget_failure`` — raised by check_budget (Budget/Config errors).
    - ``fail_store_once`` — the next store_results simulates the raced
      UNIQUE(platform, canonical_id, dish_index) violation: it returns None
      AND materializes the racer's rows (as a concurrent writer would have).
    """

    def __init__(self) -> None:
        self.jobs: dict[uuid.UUID, Job] = {}
        self.recipes: list[Recipe] = []
        self.spend_rows: list[dict[str, Any]] = []
        self.cover_misses: list[CoverMiss] = []
        # Recipes whose owner is real-covers-granted (frame backfill scope) —
        # tests add ids to opt a recipe into list_recipes_for_frame_backfill.
        self.real_covers_owner_ids: set[uuid.UUID] = set()
        self.budget_failure: Exception | None = None
        self.fail_store_once = False
        self.budget_checks = 0
        self._clock = 0

    # ── helpers for tests ────────────────────────────────────────────────────

    def _tick(self) -> datetime:
        self._clock += 1
        return _EPOCH + timedelta(seconds=self._clock)

    def seed_job(self, **overrides: Any) -> Job:
        now = self._tick()
        fields: dict[str, Any] = {
            "id": uuid.uuid4(),
            "owner_id": uuid.uuid4(),
            "type": "extract",
            "payload": {"url": "https://example.test/v", "fetch_url": "https://example.test/v"},
            "platform": "bilibili",
            "canonical_id": "BVfake000-p1",
            "status": "pending",
            "attempts": 0,
            "error_type": None,
            "error_detail": None,
            "result_recipe_ids": [],
            "created_at": now,
            "updated_at": now,
        }
        fields.update(overrides)
        job = Job(**fields)
        self.jobs[job.id] = job
        return job

    def seed_recipe(self, **overrides: Any) -> Recipe:
        fields: dict[str, Any] = {
            "id": uuid.uuid4(),
            "owner_id": uuid.uuid4(),
            "title_en": "Seeded dish",
            "title_original": "预置菜",
            "platform": "bilibili",
            "canonical_id": "BVfake000-p1",
            "source_url": "https://example.test/v",
            "dish_index": 0,
            "status": "stored",
            "tags": [],
            "user_notes": None,
            "image_url": None,
            "image_style_version": None,
            "cover_sprite_id": None,
            "estimated": None,
            "document": {},
            "extraction_meta": {},
            "created_at": self._tick(),
        }
        fields.update(overrides)
        recipe = Recipe(**fields)
        self.recipes.append(recipe)
        return recipe

    # ── JobStore surface ─────────────────────────────────────────────────────

    async def find_active_job(
        self, owner_id: uuid.UUID, platform: str, canonical_id: str
    ) -> Job | None:
        candidates = [
            job
            for job in self.jobs.values()
            if job.owner_id == owner_id
            and job.platform == platform
            and job.canonical_id == canonical_id
            and job.status in ACTIVE_STATUSES
        ]
        return min(candidates, key=lambda job: job.created_at) if candidates else None

    async def find_completed_job_with_recipes(
        self, owner_id: uuid.UUID, platform: str, canonical_id: str
    ) -> Job | None:
        # Owner-scope BOTH the recipe probe AND the stored-job filter (M2 —
        # mirrors the real PostgresJobStore, critique M2).
        if not any(
            recipe.owner_id == owner_id
            and recipe.platform == platform
            and recipe.canonical_id == canonical_id
            for recipe in self.recipes
        ):
            return None
        stored = [
            job
            for job in self.jobs.values()
            if job.owner_id == owner_id
            and job.platform == platform
            and job.canonical_id == canonical_id
            and job.status == "stored"
        ]
        return max(stored, key=lambda job: job.created_at) if stored else None

    async def insert_job(
        self,
        *,
        owner_id: uuid.UUID,
        job_type: str,
        payload: dict[str, Any],
        platform: str | None,
        canonical_id: str | None,
    ) -> Job:
        return self.seed_job(
            owner_id=owner_id,
            type=job_type,
            payload=payload,
            platform=platform,
            canonical_id=canonical_id,
        )

    async def find_active_illustration_job(self, recipe_id: uuid.UUID) -> Job | None:
        candidates = [
            job
            for job in self.jobs.values()
            if job.type == "illustration"
            and job.status in ("pending", "illustrating")
            and str(recipe_id) in (job.payload.get("recipe_ids") or [])
        ]
        return min(candidates, key=lambda job: job.created_at) if candidates else None

    async def load_recipes_for_illustration(
        self, job_id: uuid.UUID, recipe_ids: list[uuid.UUID]
    ) -> list[RecipeImageRef]:
        wanted = {str(rid) for rid in recipe_ids}
        rows = [recipe for recipe in self.recipes if str(recipe.id) in wanted]
        return [
            RecipeImageRef(
                recipe.id,
                recipe.owner_id,
                job_id,
                recipe.platform,
                recipe.canonical_id,
                recipe.dish_index,
                recipe.document,
            )
            for recipe in sorted(rows, key=lambda r: r.dish_index)
        ]

    async def get_job(self, job_id: uuid.UUID, owner_id: uuid.UUID) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            return None
        return job

    async def list_jobs(self, owner_id: uuid.UUID, limit: int = 20) -> list[Job]:
        mine = [job for job in self.jobs.values() if job.owner_id == owner_id]
        mine.sort(key=lambda job: job.updated_at, reverse=True)
        return mine[:limit]

    async def claim_next_job(self) -> Job | None:
        pending = [job for job in self.jobs.values() if job.status == "pending"]
        if not pending:
            return None
        job = min(pending, key=lambda j: j.created_at)
        job.status = "downloading"
        job.attempts += 1
        job.updated_at = self._tick()
        return job

    async def set_status(self, job_id: uuid.UUID, status: str) -> None:
        self.jobs[job_id].status = status

    async def requeue(self, job_id: uuid.UUID) -> None:
        self.jobs[job_id].status = "pending"

    async def mark_failed(self, job_id: uuid.UUID, error_type: str, error_detail: str) -> None:
        job = self.jobs[job_id]
        job.status = "failed"
        job.error_type = error_type
        job.error_detail = error_detail

    async def find_recipe_ids(
        self, owner_id: uuid.UUID, platform: str, canonical_id: str
    ) -> list[uuid.UUID]:
        rows = [
            recipe
            for recipe in self.recipes
            if recipe.owner_id == owner_id
            and recipe.platform == platform
            and recipe.canonical_id == canonical_id
        ]
        return [recipe.id for recipe in sorted(rows, key=lambda r: r.dish_index)]

    async def adopt_recipes(self, job_id: uuid.UUID, recipe_ids: list[uuid.UUID]) -> None:
        job = self.jobs[job_id]
        job.status = "stored"
        job.result_recipe_ids = list(recipe_ids)
        job.error_type = None
        job.error_detail = None

    async def store_results(
        self,
        job: Job,
        documents: list[RecipeDocument],
        estimates: list[EstimatedAttributes | None],
        tags: list[list[str]],
        cover_sprite_ids: list[str],
        *,
        extraction_meta: dict[str, Any],
    ) -> list[uuid.UUID] | None:
        if self.fail_store_once:
            # Simulate the raced duplicate: the "other writer" already
            # committed rows for this canonical identity.
            self.fail_store_once = False
            for index, document in enumerate(documents):
                self.seed_recipe(
                    owner_id=job.owner_id,
                    platform=job.platform,
                    canonical_id=job.canonical_id,
                    dish_index=index,
                    title_en=document.dish_name.en,
                    title_original=document.dish_name.original,
                    document=document.model_dump(mode="json"),
                )
            return None
        recipe_ids: list[uuid.UUID] = []
        for index, (document, estimate, dish_tags, sprite_id) in enumerate(
            zip(documents, estimates, tags, cover_sprite_ids, strict=False)
        ):
            # image_url lands NULL — a real frame / illustration is persisted
            # post-store via set_recipe_image (never inside the paid-work
            # crash-loss window). The assigned cover_sprite_id IS stored here.
            # Derived estimates ride in their own column (Hard Rule 7); auto-tags
            # seed the user-editable recipes.tags column.
            recipe = self.seed_recipe(
                owner_id=job.owner_id,
                platform=job.platform,
                canonical_id=job.canonical_id,
                source_url=job.payload["url"],
                dish_index=index,
                title_en=document.dish_name.en,
                title_original=document.dish_name.original,
                tags=dish_tags,
                cover_sprite_id=sprite_id,
                document=document.model_dump(mode="json"),
                estimated=estimate.model_dump(mode="json") if estimate is not None else None,
                extraction_meta=extraction_meta,
            )
            recipe_ids.append(recipe.id)
        job.status = "stored"
        job.result_recipe_ids = recipe_ids
        job.error_type = None
        job.error_detail = None
        return recipe_ids

    async def record_cover_misses(
        self,
        owner_id: uuid.UUID,
        entries: list[tuple[uuid.UUID | None, AssignmentMiss]],
    ) -> None:
        for recipe_id, miss in entries:
            self.cover_misses.append(
                CoverMiss(
                    owner_id=owner_id,
                    recipe_id=recipe_id,
                    dish_name_en=miss.dish_name_en,
                    dish_name_original=miss.dish_name_original,
                    cuisine_type=miss.cuisine_type,
                    tags=list(miss.tags),
                    suggested_sprite_id=miss.suggested_sprite_id,
                    resolved_sprite_id=miss.resolved_sprite_id,
                    score=miss.score,
                    reason=miss.reason,
                )
            )

    async def list_recipes_missing_sprites(self) -> list[RecipeSpriteRef]:
        return [
            RecipeSpriteRef(r.id, r.owner_id, r.document, list(r.tags))
            for r in self.recipes
            if r.cover_sprite_id is None
        ]

    async def set_recipe_sprite(self, recipe_id: uuid.UUID, sprite_id: str) -> None:
        for recipe in self.recipes:
            if recipe.id == recipe_id:
                recipe.cover_sprite_id = sprite_id

    async def list_recipes_for_frame_backfill(self) -> list[RecipeFrameRef]:
        return [
            RecipeFrameRef(
                r.id,
                r.owner_id,
                r.platform,
                r.canonical_id,
                r.dish_index,
                r.document,
                r.extraction_meta,
            )
            for r in self.recipes
            if r.image_url is None and r.owner_id in self.real_covers_owner_ids
        ]

    def _job_id_for_recipe(self, recipe_id: uuid.UUID) -> uuid.UUID | None:
        """Mirror the real inner join: the stored job whose result_recipe_ids
        lists this recipe (the illustration backfill attributes spend to it)."""
        for job in self.jobs.values():
            if recipe_id in (job.result_recipe_ids or []):
                return job.id
        return None

    async def list_recipes_missing_images(self) -> list[RecipeImageRef]:
        refs: list[RecipeImageRef] = []
        for recipe in self.recipes:
            if recipe.image_url is not None:
                continue
            job_id = self._job_id_for_recipe(recipe.id)
            if job_id is None:
                continue  # inner join drops recipes with no locatable job
            refs.append(
                RecipeImageRef(
                    recipe.id,
                    recipe.owner_id,
                    job_id,
                    recipe.platform,
                    recipe.canonical_id,
                    recipe.dish_index,
                    recipe.document,
                )
            )
        return refs

    async def set_recipe_image(
        self, recipe_id: uuid.UUID, image_url: str, style_version: str
    ) -> None:
        for recipe in self.recipes:
            if recipe.id == recipe_id:
                recipe.image_url = image_url
                recipe.image_style_version = style_version

    async def reconcile_interrupted(self) -> int:
        count = 0
        for job in self.jobs.values():
            if job.status in RUNNING_STATUSES:
                job.status = "failed"
                job.error_type = "interrupted"
                job.error_detail = "reconciled by fake store"
                count += 1
        return count

    async def check_budget(self, owner_id: uuid.UUID) -> None:
        self.budget_checks += 1
        if self.budget_failure is not None:
            raise self.budget_failure

    async def record_spend(
        self,
        *,
        job_id: uuid.UUID,
        owner_id: uuid.UUID,
        usage: ExtractionUsage,
        cost_usd: Decimal,
    ) -> None:
        self.spend_rows.append(
            {
                "job_id": job_id,
                "owner_id": owner_id,
                "model": usage.model_id,
                "tokens_in": usage.tokens_in,
                "tokens_out": usage.tokens_out,
                "tokens_thinking": usage.tokens_thinking,
                "cost_usd": cost_usd,
            }
        )
