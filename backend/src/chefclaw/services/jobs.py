"""Enqueue + the no-broker extraction worker (plan §4, §16.4, §16.10).

The worker is an asyncio task started/stopped by the app lifespan and runs
STRICTLY SERIALLY — claim one job (``FOR UPDATE SKIP LOCKED``), drive it to a
terminal state, repeat. Both that and the single-uvicorn-worker rule are hard
constraints of the no-broker design: the double-spend race is only closed at
concurrency 1.

Stage machine: ``downloading → extracting → validating → stored | failed``.
The paid stage is idempotent (re-check recipes before extract — a crash
between store and flip must not re-spend), budget-checked before EVERY model
call, and ledgered per attempt including failures.

Cancellation honesty (for the jobs ADR): per-stage deadlines use
``asyncio.wait_for``. The Bilibili adapter runs yt-dlp inside
``asyncio.to_thread`` — cancelling that awaitable abandons the thread
cooperatively (the download keeps running until yt-dlp returns; compose
``init: true`` reaps any orphaned ffmpeg). Plan §4's process-group ``killpg``
applies when downloads move to subprocess form.
"""

import asyncio
import logging
import random
import shutil
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chefclaw import errors, observability, spend
from chefclaw.config import Settings
from chefclaw.documents import SourceInfo, validate_extraction
from chefclaw.extractors import (
    ExtractionUsage,
    ExtractorAdapter,
    extractor_model_id,
    get_extractor,
)
from chefclaw.models import Job, JobStatus
from chefclaw.services.covers import (
    CoverGenerator,
    archived_video_path,
    cover_frames,
    generate_covers,
)
from chefclaw.services.repo import JobStore, RecipeCoverRef
from chefclaw.sources import CanonicalRef, FetchedMedia, SourceAdapter, resolve_source
from chefclaw.sources.localfile import LocalFileSource

logger = logging.getLogger(__name__)

__all__ = [
    "Worker",
    "default_source_adapters",
    "enqueue_extract",
    "enqueue_upload",
]

# ── Tuning constants (deliberately NOT config: these are safety bounds, not
#    knobs — change them in code with a reviewed diff) ───────────────────────
# Per-stage deadlines: a 480p cooking video downloads in well under 10 min and
# extracts in well under 15; anything longer is wedged, and the retryable
# timeout error puts the job back in line instead of blocking the serial queue.
DOWNLOAD_TIMEOUT_SECONDS = 600.0
EXTRACT_TIMEOUT_SECONDS = 900.0
MAX_ATTEMPTS = 3  # per job, counted at claim; then terminal failed (plan §4)
IDLE_SLEEP_SECONDS = 1.0  # poll cadence when the queue is empty
# Backoff after a retryable requeue, multiplied by the attempt number. Two
# distinct scales (Phase 4 polish): rate_limited means a platform/model API
# said SLOW DOWN — immediately re-poking it wastes an attempt and antagonizes
# the throttle, so it backs off in tens of seconds; every other retryable
# (transient download/extract hiccup) stays snappy.
RETRY_BACKOFF_SECONDS = 2.0
RATE_LIMITED_BACKOFF_SECONDS = 30.0
# §16.10 behavior rule: a jittered politeness delay before every PLATFORM
# fetch (skipped for 'local' — no platform is touched). Injectable sleeper
# lets tests skip the wall-clock wait.
POLITENESS_DELAY_MIN_SECONDS = 2.0
POLITENESS_DELAY_MAX_SECONDS = 5.0

_UPLOAD_STAGING_DIRNAME = "chefclaw-uploads"
_JOB_SCRATCH_DIRNAME = "chefclaw-jobs"

Sleeper = Callable[[float], Awaitable[None]]


def default_source_adapters(settings: Settings) -> list[SourceAdapter]:
    """The URL-matched platform adapters (LocalFileSource is upload-only and
    deliberately never registered — see sources/__init__.py).

    ``CHEFCLAW_SOURCES=fake`` (the golden-suite stack, plan §16.9) swaps in
    the canned FakeSource. Its platform is a REAL enum value ("bilibili")
    because document SourceInfo validation rejects a stored dish whose
    provenance platform isn't one. Any other unknown value is a typed
    ConfigError — a typo must never silently pick the real platform adapters
    (fail-closed, §16.8 pattern).
    """
    if settings.chefclaw_sources == "fake":
        from chefclaw.sources.fake import FakeSource

        return [
            FakeSource(
                platform="bilibili",
                canonical_id="fake-golden-1",
                match_prefixes=("fake://",),
            )
        ]
    if settings.chefclaw_sources != "real":
        raise errors.ConfigError(
            f"Unknown CHEFCLAW_SOURCES value {settings.chefclaw_sources!r} — "
            "expected 'real' or 'fake'."
        )
    from chefclaw.sources.bilibili import BilibiliSource
    from chefclaw.sources.rednote import RednoteSource

    return [BilibiliSource(settings), RednoteSource(settings)]


def _scratch_root(settings: Settings) -> Path:
    return Path(settings.scratch_dir) if settings.scratch_dir else Path(tempfile.gettempdir())


def upload_staging_dir(settings: Settings) -> Path:
    """Where uploaded files live (content-addressed) until their job ends."""
    return _scratch_root(settings) / _UPLOAD_STAGING_DIRNAME


# ─── Enqueue (dedupe gates BEFORE any job exists — §16.1/16.2) ───────────────


async def _dedupe_or_insert(
    store: JobStore,
    *,
    owner_id: uuid.UUID,
    job_type: str,
    ref: CanonicalRef,
    payload: dict[str, Any],
) -> tuple[Job, bool]:
    """Shared dedupe: an ACTIVE job for this canonical identity wins; else a
    completed job whose recipes still exist wins; else insert pending.
    Returns ``(job, existing)``."""
    active = await store.find_active_job(ref.platform, ref.canonical_id)
    if active is not None:
        return active, True
    completed = await store.find_completed_job_with_recipes(ref.platform, ref.canonical_id)
    if completed is not None:
        return completed, True
    job = await store.insert_job(
        owner_id=owner_id,
        job_type=job_type,
        payload=payload,
        platform=ref.platform,
        canonical_id=ref.canonical_id,
    )
    return job, False


async def enqueue_extract(
    store: JobStore,
    owner_id: uuid.UUID,
    url: str,
    adapters: Sequence[SourceAdapter],
    settings: Settings,
) -> tuple[Job, bool]:
    """Resolve → dedupe on canonical identity → insert pending (or return the
    existing job). Raises UnsupportedUrlError (→ 400), ConfigError (→ 503,
    e.g. Rednote pasted while the sidecar is unset — fail at enqueue, not
    minutes later in the worker), DownloadFailedError (short-link resolution)."""
    adapter = resolve_source(url, adapters)  # UnsupportedUrlError propagates
    if adapter.platform == "rednote" and not settings.xhs_sidecar_url:
        raise errors.ConfigError(
            "XHS_SIDECAR_URL is not set — the Rednote source is disabled "
            "(fail-closed; see docs/SERVICES.md)"
        )
    ref = await adapter.resolve(url)
    # fetch_url rides in the payload so retries never re-resolve (Rednote
    # xsec_token URLs are per-share; the resolved one is the good one).
    payload = {"url": url, "fetch_url": ref.fetch_url}
    return await _dedupe_or_insert(
        store, owner_id=owner_id, job_type="extract", ref=ref, payload=payload
    )


async def enqueue_upload(
    store: JobStore,
    owner_id: uuid.UUID,
    file_path: Path,
    provenance_url: str | None,
    platform_hint: str | None,
    settings: Settings,
    *,
    original_filename: str | None = None,
) -> tuple[Job, bool]:
    """The §16.10 tier-2 floor: ingest (hash + content-addressed copy into
    staging) then the same canonical dedupe — re-uploading the same bytes
    returns the existing job/recipes exactly like a re-pasted URL."""
    source = LocalFileSource(dest_dir=upload_staging_dir(settings))
    ref, media = await source.ingest(file_path, provenance_url, platform_hint)
    payload = {
        "url": ref.fetch_url,  # provenance_url or local://<canonical_id>
        "fetch_url": ref.fetch_url,
        "video_path": str(media.video_path),
        "provenance_url": provenance_url,
        "platform_hint": platform_hint,
        "original_filename": original_filename or file_path.name,
        "sha256": media.extra.get("sha256"),
    }
    return await _dedupe_or_insert(
        store, owner_id=owner_id, job_type="upload", ref=ref, payload=payload
    )


# ─── The worker ──────────────────────────────────────────────────────────────


class Worker:
    """The strictly-serial in-process job worker (one instance per api
    process, one api process per stack — hard constraints, not knobs)."""

    def __init__(
        self,
        store: JobStore,
        adapters: Sequence[SourceAdapter],
        settings: Settings,
        *,
        extractor_factory: Callable[[Settings], ExtractorAdapter] = get_extractor,
        cover_generator: CoverGenerator = generate_covers,
        backfill_covers_on_start: bool = False,
        sleeper: Sleeper = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        idle_seconds: float = IDLE_SLEEP_SECONDS,
    ) -> None:
        self.store = store
        self._adapters_by_platform = {adapter.platform: adapter for adapter in adapters}
        self._settings = settings
        self._extractor_factory = extractor_factory
        # Injectable like the sleeper: CI-tier tests must never shell out to
        # real ffmpeg. The backfill flag defaults OFF (tests); the app turns
        # it on for the one-shot startup pass.
        self._cover_generator = cover_generator
        self._backfill_covers_on_start = backfill_covers_on_start
        # The one-shot backfill's task handle (run_forever spawns it in the
        # background) — exposed for tests and cancelled on worker shutdown.
        self.backfill_task: asyncio.Task[None] | None = None
        self._sleeper = sleeper
        self._jitter = jitter
        self._idle_seconds = idle_seconds

    # ── loop ─────────────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Reconcile once, then claim→process→repeat. Never dies on a DB
        hiccup (compose boots services in parallel; CI smoke has no DB at
        all) — it just idles and retries."""
        reconciled = False
        try:
            while True:
                if not reconciled:
                    try:
                        flipped = await self.store.reconcile_interrupted()
                        if flipped:
                            logger.warning("reconciled %d interrupted job(s) to failed", flipped)
                        reconciled = True
                    except Exception:
                        logger.debug("startup reconcile failed (db not up yet?)", exc_info=True)
                        await self._sleeper(self._idle_seconds)
                        continue
                    if self._backfill_covers_on_start and self.backfill_task is None:
                        # One-shot, best-effort, never raises — spawned in the
                        # BACKGROUND so a slow ffmpeg pass never delays the
                        # first claim. Job execution stays strictly serial:
                        # the backfill only runs ffmpeg subprocesses + row
                        # updates, which is acceptable concurrency.
                        self.backfill_task = asyncio.create_task(
                            self.backfill_covers(), name="chefclaw-cover-backfill"
                        )
                try:
                    job = await self.store.claim_next_job()
                except Exception:
                    logger.warning("job claim failed; retrying", exc_info=True)
                    await self._sleeper(self._idle_seconds)
                    continue
                if job is None:
                    await self._sleeper(self._idle_seconds)
                    continue
                try:
                    await self.process(job)
                except Exception as exc:
                    # process() only leaks an exception when the STORE itself
                    # failed (db outage mid-job: set_status/requeue/mark_failed
                    # raised). The job is left mid-stage for the next boot's
                    # reconcile — but the worker task MUST survive: a dead task
                    # means no job ever runs again while the api looks healthy.
                    logger.exception(
                        "job %s processing leaked an error (db outage?); "
                        "leaving it mid-stage for reconcile",
                        job.id,
                        extra={"job_id": str(job.id), "stage": "store"},
                    )
                    observability.capture_job_failure(
                        exc,
                        job_id=job.id,
                        stage="store",
                        error_type="store_failure",
                        platform=job.platform,
                        attempt=job.attempts,
                    )
                    await self._sleeper(self._idle_seconds)
        finally:
            # Worker shutdown takes the backfill with it (best-effort work —
            # the next boot's backfill picks up whatever it left missing).
            if self.backfill_task is not None:
                self.backfill_task.cancel()

    # ── one job, claim to terminal ───────────────────────────────────────────

    async def process(self, job: Job) -> None:
        """Drive one claimed job to a terminal state (or a requeue).

        Never raises except CancelledError (shutdown mid-job): then the job
        is deliberately LEFT in its running stage for the next boot's
        reconcile to flip to ``interrupted`` — restart must not look like a
        retryable failure."""
        scratch_dir = _scratch_root(self._settings) / _JOB_SCRATCH_DIRNAME / str(job.id)
        stage = "download"
        terminal = True
        started = time.perf_counter()
        job_extra = {
            "job_id": str(job.id),
            "job_type": job.type,
            "platform": job.platform,
            "attempt": job.attempts,
        }
        logger.info(
            "job %s claimed (%s/%s, attempt %d)",
            job.id, job.type, job.platform, job.attempts,
            extra=job_extra,
        )
        try:
            media = await self._download(job, scratch_dir)
            logger.info(
                "job %s download stage done",
                job.id,
                extra={**job_extra, "stage": "download",
                       "duration_ms": round((time.perf_counter() - started) * 1000, 1)},
            )
            stage = "extract"
            await self._extract_validate_store(job, media)
            logger.info(
                "job %s stored (attempt %d)",
                job.id, job.attempts,
                extra={**job_extra, "stage": "stored",
                       "duration_ms": round((time.perf_counter() - started) * 1000, 1)},
            )
        except asyncio.CancelledError:
            terminal = False  # reconcile owns this on next boot
            raise
        except errors.ChefclawError as err:
            if err.retryable and job.attempts < MAX_ATTEMPTS:
                terminal = False
                logger.warning(
                    "job %s attempt %d failed (%s), requeueing: %s",
                    job.id, job.attempts, err.error_type, err,
                    extra={**job_extra, "stage": stage, "error_type": err.error_type},
                )
                # A breadcrumb, not an issue — retries annotate the eventual
                # terminal failure instead of paging on their own.
                observability.add_job_breadcrumb(
                    f"attempt {job.attempts} requeued ({err.error_type})",
                    job_id=job.id,
                    stage=stage,
                    error_type=err.error_type,
                )
                await self.store.requeue(job.id)
                # Linear backoff, scaled per error type (rate_limited backs
                # off much harder — see the constants above); the loop is
                # serial so this simply delays the next claim (created_at
                # ordering keeps fairness).
                backoff = (
                    RATE_LIMITED_BACKOFF_SECONDS
                    if err.error_type == "rate_limited"
                    else RETRY_BACKOFF_SECONDS
                )
                await self._sleeper(backoff * job.attempts)
            else:
                logger.warning(
                    "job %s failed terminally (%s) after %d attempt(s): %s",
                    job.id, err.error_type, job.attempts, err,
                    extra={**job_extra, "stage": stage, "error_type": err.error_type},
                )
                observability.capture_job_failure(
                    err,
                    job_id=job.id,
                    stage=stage,
                    error_type=err.error_type,
                    platform=job.platform,
                    attempt=job.attempts,
                )
                await self.store.mark_failed(job.id, err.error_type, str(err))
        except Exception as exc:
            # Untyped leak (the gemini adapter can surface httpx errors,
            # FileNotFoundError, …): assign a stage-appropriate type; terminal
            # (an unknown error must not silently burn paid retries).
            error_type = "extraction_failed" if stage == "extract" else "download_failed"
            logger.exception(
                "job %s hit an untyped error in %s stage",
                job.id, stage,
                extra={**job_extra, "stage": stage, "error_type": error_type},
            )
            observability.capture_job_failure(
                exc,
                job_id=job.id,
                stage=stage,
                error_type=error_type,
                platform=job.platform,
                attempt=job.attempts,
            )
            await self.store.mark_failed(
                job.id, error_type, f"{type(exc).__name__}: {exc}"
            )
        finally:
            self._cleanup(scratch_dir, job, terminal)

    # ── stages ───────────────────────────────────────────────────────────────

    async def _download(self, job: Job, scratch_dir: Path) -> FetchedMedia:
        if job.type == "upload":
            video_path = Path(job.payload["video_path"])
            if not video_path.is_file():
                raise errors.DownloadFailedError(
                    f"staged upload file is gone: {video_path} — re-upload the video"
                )
            return FetchedMedia(
                video_path=video_path,
                title=None,
                creator=None,
                duration_seconds=None,
                extra={
                    "provenance_url": job.payload.get("provenance_url"),
                    "platform_hint": job.payload.get("platform_hint"),
                    "original_filename": job.payload.get("original_filename"),
                },
            )

        adapter = self._adapters_by_platform.get(job.platform or "")
        if adapter is None:
            raise errors.ConfigError(
                f"no source adapter registered for platform {job.platform!r}"
            )
        ref = CanonicalRef(
            platform=job.platform,
            canonical_id=job.canonical_id,
            fetch_url=job.payload["fetch_url"],
        )
        await self._politeness_delay(job.platform)
        try:
            return await asyncio.wait_for(
                adapter.fetch(ref, scratch_dir), DOWNLOAD_TIMEOUT_SECONDS
            )
        except TimeoutError:
            raise errors.DownloadFailedError(
                f"download timed out after {DOWNLOAD_TIMEOUT_SECONDS:.0f}s"
            ) from None

    async def _politeness_delay(self, platform: str | None) -> None:
        """§16.10: jittered per-request delay before touching a platform.
        'local' touches nothing; tests inject a no-op sleeper."""
        if platform == "local":
            return
        span = POLITENESS_DELAY_MAX_SECONDS - POLITENESS_DELAY_MIN_SECONDS
        await self._sleeper(POLITENESS_DELAY_MIN_SECONDS + span * self._jitter())

    async def _extract_validate_store(self, job: Job, media: FetchedMedia) -> list[uuid.UUID]:
        await self.store.set_status(job.id, JobStatus.EXTRACTING.value)
        logger.info(
            "job %s extracting", job.id,
            extra={"job_id": str(job.id), "stage": "extract"},
        )

        # IDEMPOTENT PAID STAGE (§4): a crash between store and flip left
        # recipes behind — adopt them, never re-spend.
        existing_ids = await self.store.find_recipe_ids(job.platform, job.canonical_id)
        if existing_ids:
            logger.info("job %s adopting %d pre-existing recipe(s)", job.id, len(existing_ids))
            await self.store.adopt_recipes(job.id, existing_ids)
            return existing_ids

        # Budget gate FIRST (cheap, no write), immediately before the paid
        # call — retries pass through here again by construction.
        await self.store.check_budget(job.owner_id)
        extractor = self._extractor_factory(self._settings)  # ConfigError ⇒ terminal

        try:
            outcome = await asyncio.wait_for(
                extractor.extract(media.video_path, media.title, media.duration_seconds),
                EXTRACT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            await self._record_attempt(job, usage=None)
            raise errors.ExtractionFailedError(
                f"extraction timed out after {EXTRACT_TIMEOUT_SECONDS:.0f}s"
            ) from None
        except (errors.ExtractionFailedError, errors.RateLimitedError) as err:
            # The call reached the model and may have consumed tokens. When
            # the adapter salvaged usage from the failing response (a billed
            # 429 / unparseable output), ledger the REAL tokens; otherwise
            # write zeros — the row itself is what counts either way (the
            # daily cap counts rows).
            await self._record_attempt(job, usage=err.usage)
            raise
        except errors.ChefclawError:
            # Remaining typed errors (ConfigError: auth rejected before any
            # tokens) never reached the API — no ledger row, per the
            # record_spend contract.
            raise
        except Exception:
            # UNTYPED leak (httpx transport error mid-call, SDK bug): the
            # request may have reached the API and burned tokens we can't see.
            # Fail closed — ledger the attempt so the daily cap still counts
            # it. (CancelledError is BaseException and passes through above.)
            await self._record_attempt(job, usage=None)
            raise

        await self._record_attempt(job, usage=outcome.usage)

        await self.store.set_status(job.id, JobStatus.VALIDATING.value)
        logger.info(
            "job %s validating (%d dish(es))", job.id, len(outcome.dishes),
            extra={"job_id": str(job.id), "stage": "validate"},
        )
        # Provenance is pipeline truth (documents.validate_extraction
        # overwrites any model-emitted source block).
        source = SourceInfo(
            platform=job.platform,
            url=job.payload["url"],
            creator=media.creator,
            video_duration_seconds=media.duration_seconds,
        )
        documents = validate_extraction(outcome.dishes, source)

        extraction_meta: dict[str, Any] = {
            "model_id": outcome.usage.model_id,
            "prompt_version": outcome.usage.prompt_version,
            "warnings": list(outcome.warnings),
            "media_resolution": self._settings.gemini_media_resolution,
            "extracted_at": datetime.now(UTC).isoformat(),
            "tokens": {
                "in": outcome.usage.tokens_in,
                "out": outcome.usage.tokens_out,
                "thinking": outcome.usage.tokens_thinking,
            },
        }
        retained, retention_warnings = self._retain_media(job, media)
        if retained:
            extraction_meta["retained_media"] = retained
        if retention_warnings:
            extraction_meta["warnings"].extend(retention_warnings)

        # The atomic store comes FIRST — covers must never sit inside the
        # paid-work crash-loss window (a wedged ffmpeg before the store would
        # reconcile to interrupted and a human retry would re-pay).
        recipe_ids = await self.store.store_results(
            job, documents, extraction_meta=extraction_meta
        )
        if recipe_ids is None:
            # UNIQUE(platform, canonical_id, dish_index) fired: a raced
            # duplicate landed first — adopt its rows, never error (§16.2).
            recipe_ids = await self.store.find_recipe_ids(job.platform, job.canonical_id)
            if not recipe_ids:
                err = errors.ExtractionFailedError(
                    "store hit a duplicate-key conflict but no recipes exist for "
                    f"({job.platform}, {job.canonical_id}) — inconsistent datastore"
                )
                # A storage-integrity failure is DETERMINISTIC: retrying would
                # burn a real paid model call per attempt on a store that will
                # fail identically. Terminal, first attempt (fail-closed).
                err.retryable = False
                raise err
            await self.store.adopt_recipes(job.id, recipe_ids)
            return recipe_ids  # the racer's rows — their own cover pass owns them
        # Covers AFTER the commit: best-effort, and a crash between the store
        # and here is healed by the startup backfill (its documented job).
        await self._store_covers(job, media, retained, recipe_ids)
        return recipe_ids

    async def _record_attempt(self, job: Job, usage: ExtractionUsage | None) -> None:
        """One llm_spend row per model attempt, INCLUDING failures. When the
        adapter raised without token accounting we record zeros — the row
        still counts against the daily attempt cap, which is the guard that
        bounds runaway retries."""
        if usage is None:
            usage = ExtractionUsage(
                model_id=extractor_model_id(self._settings),
                prompt_version="unknown",
                tokens_in=0,
                tokens_out=0,
                tokens_thinking=0,
            )
        await self.store.record_spend(
            job_id=job.id,
            owner_id=job.owner_id,
            usage=usage,
            cost_usd=spend.estimate_cost(usage),
        )

    # ── covers (poster keyframes — strictly best-effort, post-store) ─────────

    def _media_root(self) -> Path:
        # resolve() so every persisted cover_path is absolute — the /cover
        # route serves only files that resolve under this same root.
        return Path(self._settings.media_dir).resolve()

    async def _store_covers(
        self, job: Job, media: FetchedMedia, retained: list[str], recipe_ids: Sequence[uuid.UUID]
    ) -> None:
        """One poster keyframe per dish, generated AFTER the atomic store and
        persisted per row via set_recipe_cover. STRICTLY BEST-EFFORT: any
        failure just leaves cover_path NULL (the backfill may heal it later).
        Covers come from the RETAINED archive file ONLY — with
        media_retention=discard nothing is ever written under media_dir
        (has_cover simply stays false, e.g. the golden/CI stacks)."""
        if self._settings.media_retention != "keep":
            return
        try:
            video_path = self._cover_source_video(media, retained)
            if video_path is None:
                return
            target_dir = self._media_root() / job.platform / job.canonical_id
            dish_count = len(recipe_ids)
            await self._generate_and_persist_covers(
                video_path,
                target_dir,
                cover_frames(dish_count),
                dict(enumerate(recipe_ids)),
            )
        except Exception:
            logger.warning(
                "job %s cover generation failed; recipes stored without covers",
                job.id,
                exc_info=True,
            )

    @staticmethod
    def _cover_source_video(media: FetchedMedia, retained: list[str]) -> Path | None:
        # media_retention=keep MOVED the download into the archive — the
        # retained entry with the download's filename is the video. No scratch
        # fallback: covers are generated from the retained archive file only.
        for entry in retained:
            path = Path(entry)
            if path.name == media.video_path.name and path.is_file():
                return path
        return None

    async def _generate_and_persist_covers(
        self,
        video_path: Path,
        target_dir: Path,
        frames: Sequence[tuple[int, float]],
        recipe_id_by_dish: Mapping[int, uuid.UUID],
    ) -> int:
        """The shared generate→persist path (live post-store stage AND the
        startup backfill): run the generator once for ``frames``, then point
        each produced cover-<dish_index>.jpg at its recipe row. Returns how
        many covers landed."""
        covers = await self._cover_generator(video_path, target_dir, frames)
        persisted = 0
        for dish_index, cover in covers.items():
            recipe_id = recipe_id_by_dish.get(dish_index)
            if cover is None or recipe_id is None:
                continue
            await self.store.set_recipe_cover(recipe_id, cover)
            persisted += 1
        return persisted

    async def backfill_covers(self) -> None:
        """One-shot startup backfill (best-effort): any recipe missing a cover
        — stored before the cover stage existed, OR stored by a run that
        crashed between the atomic store and its post-store cover pass — gets
        a poster keyframe from its retained archive video. Never raises — a
        failed backfill must never take the worker down."""
        try:
            missing = await self.store.list_recipes_missing_covers()
            if not missing:
                return
            # TRUE dish count per group (covered siblings included): a
            # partially-covered group keeps the same (i+1)/(N+1) spread its
            # existing covers were cut at.
            dish_counts = await self.store.group_dish_counts()
        except Exception:
            logger.warning("cover backfill: could not list recipes", exc_info=True)
            return
        generated = skipped = 0
        groups: dict[tuple[str, str], list[RecipeCoverRef]] = {}
        for recipe in missing:
            groups.setdefault((recipe.platform, recipe.canonical_id), []).append(recipe)
        media_root = self._media_root()
        for (platform, canonical_id), recipes in groups.items():
            try:
                media_dir = media_root / platform / canonical_id
                video_path = archived_video_path(media_dir)
                if video_path is None:
                    skipped += len(recipes)
                    continue
                dish_count = dish_counts.get(
                    (platform, canonical_id),
                    max(recipe.dish_index for recipe in recipes) + 1,
                )
                # Only the MISSING dishes are generated — sibling covers that
                # already exist are never overwritten.
                landed = await self._generate_and_persist_covers(
                    video_path,
                    media_dir,
                    cover_frames(dish_count, [recipe.dish_index for recipe in recipes]),
                    {recipe.dish_index: recipe.id for recipe in recipes},
                )
                generated += landed
                skipped += len(recipes) - landed
            except Exception:
                skipped += len(recipes)
                logger.warning(
                    "cover backfill failed for (%s, %s)", platform, canonical_id, exc_info=True
                )
        logger.info("cover backfill: %d generated, %d skipped", generated, skipped)

    # ── media retention (§4, MEDIA_RETENTION knob) ───────────────────────────

    def _retain_media(self, job: Job, media: FetchedMedia) -> tuple[list[str], list[str]]:
        """keep ⇒ move the fetched file(s) into the retained archive
        ({media_dir}/{platform}/{canonical_id}/); discard ⇒ leave them for
        scratch cleanup. Failures are WARNINGS, never job failures (the
        recipes matter more than the archive copy)."""
        if self._settings.media_retention != "keep":
            return [], []
        candidates: list[Path] = [media.video_path]
        for extra_path in media.extra.get("media_paths", []) or []:
            path = Path(extra_path)
            if path not in candidates:
                candidates.append(path)
        target_dir = Path(self._settings.media_dir) / job.platform / job.canonical_id
        retained: list[str] = []
        warnings: list[str] = []
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return [], [f"media retention skipped — cannot create {target_dir}: {exc}"]
        for path in candidates:
            if not path.is_file():
                continue
            destination = target_dir / path.name
            try:
                if destination.exists():
                    destination.unlink()
                shutil.move(str(path), str(destination))
                retained.append(str(destination))
            except OSError as exc:
                warnings.append(f"media retention failed for {path.name}: {exc}")
        return retained, warnings

    def _cleanup(self, scratch_dir: Path, job: Job, terminal: bool) -> None:
        """The per-job scratch subdir is ALWAYS cleaned; a terminal upload job
        also releases its content-addressed staging file (kept across
        requeues so retries don't need a re-upload)."""
        shutil.rmtree(scratch_dir, ignore_errors=True)
        if terminal and job.type == "upload":
            staged = job.payload.get("video_path")
            if staged:
                Path(staged).unlink(missing_ok=True)
