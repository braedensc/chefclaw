"""Worker + enqueue tests — CI tier: no network, no database.

The persistence seam (tests/fakes.FakeJobStore) stands in for postgres; the
config-selectable FakeSource/FakeExtractor drive every taxonomy path. The
real store's SQL (SKIP LOCKED claim, atomic store, IntegrityError adopt) is
exercised by the golden DB tier (test_worker_db.py, `-m golden`).
"""

import asyncio
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest

from chefclaw import errors
from chefclaw.config import Settings
from chefclaw.extractors import ExtractionUsage
from chefclaw.extractors.fake import FakeExtractor, default_dish
from chefclaw.models import Job
from chefclaw.services import jobs as jobs_module
from chefclaw.services.jobs import Worker, enqueue_extract, enqueue_upload
from chefclaw.sources.fake import FakeSource
from tests.fakes import FakeJobStore

OWNER_ID = uuid.UUID("01890000-0000-7000-8000-000000000001")
FAKE_URL = "https://fake.example/video/1"


class RecordingSleeper:
    """Injectable no-op sleeper: politeness/backoff without wall-clock."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class FakeCoverGenerator:
    """Injectable cover generator: writes real cover-<dish_index>.jpg files
    without ever touching ffmpeg (CI tier). Records calls for path/frame
    asserts; ``hang`` blocks forever (store-before-covers / backfill tests)."""

    def __init__(
        self, fail: bool = False, error: Exception | None = None, hang: bool = False
    ) -> None:
        self.fail = fail
        self.error = error
        self.hang = hang
        self.calls: list[tuple[Path, Path, list[tuple[int, float]]]] = []

    async def __call__(
        self, video_path: Path, target_dir: Path, frames: Sequence[tuple[int, float]]
    ) -> dict[int, str | None]:
        self.calls.append((video_path, target_dir, list(frames)))
        if self.hang:
            await asyncio.Event().wait()  # blocks until cancelled
        if self.error is not None:
            raise self.error
        if self.fail:
            return {index: None for index, _ in frames}
        target_dir.mkdir(parents=True, exist_ok=True)
        covers: dict[int, str | None] = {}
        for index, _fraction in frames:
            out_path = target_dir / f"cover-{index}.jpg"
            out_path.write_bytes(b"fake jpeg bytes")
            covers[index] = str(out_path)
        return covers


def make_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        chefclaw_api_token="test-token",
        monthly_llm_budget_usd="10",
        max_extraction_attempts_per_day="25",
        chefclaw_extractor="fake",
        media_retention="discard",
        scratch_dir=str(tmp_path / "scratch"),
        media_dir=str(tmp_path / "media"),
    )
    defaults.update(overrides)
    return Settings(**defaults)


def make_source(**overrides) -> FakeSource:
    defaults = dict(platform="bilibili", canonical_id="BVtest00001-p1")
    defaults.update(overrides)
    return FakeSource(**defaults)


def make_worker(
    store: FakeJobStore,
    source: FakeSource,
    settings: Settings,
    extractor: FakeExtractor,
    cover_generator: FakeCoverGenerator | None = None,
) -> tuple[Worker, RecordingSleeper]:
    sleeper = RecordingSleeper()
    worker = Worker(
        store=store,
        adapters=[source],
        settings=settings,
        extractor_factory=lambda _settings: extractor,
        cover_generator=cover_generator or FakeCoverGenerator(),  # never real ffmpeg in CI
        sleeper=sleeper,
        jitter=lambda: 0.25,  # deterministic politeness delay: 2 + 3*0.25 = 2.75
    )
    return worker, sleeper


async def claim_and_process(worker: Worker, store: FakeJobStore) -> Job:
    job = await store.claim_next_job()
    assert job is not None, "expected a pending job to claim"
    await worker.process(job)
    return job


# ─── enqueue: dedupe gates the paid call (§16.1/16.2) ────────────────────────


async def test_enqueue_new_job_is_pending_with_canonical_identity(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    job, existing = await enqueue_extract(
        store, OWNER_ID, FAKE_URL, [source], make_settings(tmp_path)
    )
    assert existing is False
    assert job.status == "pending"
    assert job.type == "extract"
    assert (job.platform, job.canonical_id) == ("bilibili", "BVtest00001-p1")
    assert job.payload == {"url": FAKE_URL, "fetch_url": FAKE_URL}


async def test_enqueue_duplicate_returns_active_job(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    first, _ = await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    # A DIFFERENT raw URL resolving to the same canonical id still dedupes.
    second, existing = await enqueue_extract(
        store, OWNER_ID, "https://fake.example/video/1?share=xyz", [source], settings
    )
    assert existing is True
    assert second.id == first.id
    assert len(store.jobs) == 1


async def test_enqueue_duplicate_returns_completed_job_with_recipes(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    done = store.seed_job(status="stored", canonical_id="BVtest00001-p1")
    store.seed_recipe(canonical_id="BVtest00001-p1")
    job, existing = await enqueue_extract(
        store, OWNER_ID, FAKE_URL, [source], make_settings(tmp_path)
    )
    assert existing is True
    assert job.id == done.id


async def test_enqueue_after_hard_delete_reextracts(tmp_path: Path) -> None:
    """Hard-deleted recipes re-open extraction: a stored job with NO recipes
    left does not dedupe."""
    store, source = FakeJobStore(), make_source()
    old = store.seed_job(status="stored", canonical_id="BVtest00001-p1")
    job, existing = await enqueue_extract(
        store, OWNER_ID, FAKE_URL, [source], make_settings(tmp_path)
    )
    assert existing is False
    assert job.id != old.id


async def test_enqueue_unsupported_url_raises(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    with pytest.raises(errors.UnsupportedUrlError):
        await enqueue_extract(
            store, OWNER_ID, "https://unknown.example/x", [source], make_settings(tmp_path)
        )
    assert store.jobs == {}


async def test_enqueue_rednote_without_sidecar_is_config_error(tmp_path: Path) -> None:
    """Fail at enqueue (503), not minutes later in the worker."""
    store = FakeJobStore()
    source = make_source(platform="rednote", canonical_id="a" * 24)
    with pytest.raises(errors.ConfigError, match="XHS_SIDECAR_URL"):
        await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], make_settings(tmp_path))
    assert store.jobs == {}
    assert source.resolve_calls == []  # refused before any platform touch


async def test_enqueue_upload_and_rehash_dedupe(tmp_path: Path) -> None:
    """Uploading the same bytes twice (different filenames) hits the
    content-addressed canonical id and returns the existing job."""
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    first_file = tmp_path / "dinner.mp4"
    first_file.write_bytes(b"same video bytes")
    job, existing = await enqueue_upload(
        store, OWNER_ID, first_file, "https://example.test/post", "rednote", settings
    )
    assert existing is False
    assert job.type == "upload"
    assert job.platform == "local"
    assert job.canonical_id.startswith("file-")
    assert job.payload["url"] == "https://example.test/post"
    assert Path(job.payload["video_path"]).is_file()

    second_file = tmp_path / "renamed-copy.mp4"
    second_file.write_bytes(b"same video bytes")
    again, existing = await enqueue_upload(store, OWNER_ID, second_file, None, None, settings)
    assert existing is True
    assert again.id == job.id
    assert len(store.jobs) == 1


# ─── the stage machine, happy path ───────────────────────────────────────────


async def test_happy_path_multi_dish_atomic_store(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    dish_two = default_dish()
    dish_two["dish_name"] = {"en": "Second dish", "original": "第二道菜"}
    extractor = FakeExtractor(dishes=[default_dish(), dish_two])
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    assert job.attempts == 1
    assert len(job.result_recipe_ids) == 2
    assert [r.dish_index for r in store.recipes] == [0, 1]
    assert store.recipes[1].title_en == "Second dish"
    # Provenance is pipeline truth, never model output:
    assert store.recipes[0].document["source"]["platform"] == "bilibili"
    assert store.recipes[0].document["source"]["url"] == FAKE_URL
    assert store.recipes[0].source_url == FAKE_URL
    # extraction_meta carries the §16.4-adjacent audit fields:
    meta = store.recipes[0].extraction_meta
    assert meta["model_id"] == "fake-extractor"
    assert meta["prompt_version"] == "v1"
    assert meta["tokens"] == {"in": 1000, "out": 250, "thinking": 0}
    assert "extracted_at" in meta and "media_resolution" in meta
    # One ledger row for the one successful attempt:
    assert len(store.spend_rows) == 1
    assert store.spend_rows[0]["tokens_in"] == 1000
    # Per-job scratch is always cleaned:
    assert not (tmp_path / "scratch" / "chefclaw-jobs" / str(job.id)).exists()


async def test_upload_job_end_to_end_local_platform(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    video = tmp_path / "saved.mp4"
    video.write_bytes(b"uploaded video")
    await enqueue_upload(store, OWNER_ID, video, None, None, settings)

    extractor = FakeExtractor()
    worker, sleeper = make_worker(store, make_source(), settings, extractor)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    assert store.recipes[0].platform == "local"
    assert store.recipes[0].document["source"]["platform"] == "local"
    assert sleeper.calls == []  # politeness delay skipped for 'local'
    # Terminal upload job releases its content-addressed staging file:
    assert not Path(job.payload["video_path"]).exists()


# ─── budget: fail-closed, refused BEFORE the paid call ───────────────────────


@pytest.mark.parametrize(
    ("failure", "expected_type", "detail_match"),
    [
        (errors.BudgetExceededError("monthly LLM budget reached: $10 spent"), "budget_exceeded",
         "monthly"),
        (errors.BudgetExceededError("daily extraction attempt cap reached: 25 attempts today"),
         "budget_exceeded", "attempts"),
        (errors.ConfigError("MONTHLY_LLM_BUDGET_USD is unset"), "config_error",
         "MONTHLY_LLM_BUDGET_USD"),
    ],
)
async def test_budget_gate_refuses_before_extract(
    tmp_path: Path, failure: Exception, expected_type: str, detail_match: str
) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    store.budget_failure = failure
    extractor = FakeExtractor()
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "failed"
    assert job.error_type == expected_type
    assert detail_match in job.error_detail
    assert extractor.calls == []  # the paid call NEVER happened
    assert store.spend_rows == []  # and nothing was ledgered
    assert store.budget_checks == 1


async def test_idempotent_paid_stage_adopts_orphaned_recipes(tmp_path: Path) -> None:
    """Crash between store and flip: recipes exist, job re-runs — adopt,
    never re-spend."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    orphan = store.seed_recipe(canonical_id="BVtest00001-p1")
    extractor = FakeExtractor()
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    # (enqueue deduped against the stored recipes? No stored JOB exists, so a
    # fresh job was inserted — exactly the crash-recovery shape.)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    assert job.result_recipe_ids == [orphan.id]
    assert extractor.calls == []
    assert store.spend_rows == []
    assert store.budget_checks == 0  # adopted before even reaching the gate


# ─── retries, attempt caps, taxonomy terminal states ─────────────────────────


async def test_retryable_download_failure_requeues_then_succeeds(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    source.fail_fetch(errors.DownloadFailedError("cdn hiccup"), times=1)
    extractor = FakeExtractor()
    worker, sleeper = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)
    assert job.status == "pending"  # requeued, not failed
    assert job.attempts == 1
    assert jobs_module.RETRY_BACKOFF_SECONDS * 1 in sleeper.calls  # backoff slept

    job = await claim_and_process(worker, store)
    assert job.status == "stored"
    assert job.attempts == 2
    assert len(store.spend_rows) == 1  # only the successful attempt reached the model


async def test_retryable_failures_cap_at_three_attempts(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = FakeExtractor(failure=errors.RateLimitedError("model throttled"))
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)
    assert (job.status, job.attempts) == ("pending", 1)
    job = await claim_and_process(worker, store)
    assert (job.status, job.attempts) == ("pending", 2)
    job = await claim_and_process(worker, store)
    assert (job.status, job.attempts) == ("failed", 3)
    assert job.error_type == "rate_limited"
    # EVERY model attempt was ledgered, including all three failures:
    assert len(store.spend_rows) == 3
    assert store.budget_checks == 3  # and each retry re-passed the gate first


def test_backoff_constants_pinned() -> None:
    """Phase 4 polish: rate_limited backs off on a DISTINCT, much slower scale
    than other retryables. These are safety bounds — change them in code with
    a reviewed diff, and update this pin deliberately."""
    assert jobs_module.RETRY_BACKOFF_SECONDS == 2.0
    assert jobs_module.RATE_LIMITED_BACKOFF_SECONDS == 30.0


async def test_rate_limited_backoff_is_slower_and_scales_with_attempts(
    tmp_path: Path,
) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = FakeExtractor(failure=errors.RateLimitedError("model throttled"))
    worker, sleeper = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    await claim_and_process(worker, store)  # attempt 1 → requeue
    assert jobs_module.RATE_LIMITED_BACKOFF_SECONDS * 1 in sleeper.calls
    await claim_and_process(worker, store)  # attempt 2 → requeue
    assert jobs_module.RATE_LIMITED_BACKOFF_SECONDS * 2 in sleeper.calls
    # And the ordinary retry scale was never used for a rate-limit:
    assert jobs_module.RETRY_BACKOFF_SECONDS * 1 not in sleeper.calls


async def test_other_retryable_backoff_stays_on_the_fast_scale(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    source.fail_fetch(errors.DownloadFailedError("cdn hiccup"), times=1)
    worker, sleeper = make_worker(store, source, settings, FakeExtractor())

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    await claim_and_process(worker, store)  # attempt 1 → requeue

    assert jobs_module.RETRY_BACKOFF_SECONDS * 1 in sleeper.calls
    assert jobs_module.RATE_LIMITED_BACKOFF_SECONDS * 1 not in sleeper.calls


async def test_cookies_expired_is_terminal_first_attempt(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    source.fail_fetch(errors.CookiesExpiredError("session invalid"))
    worker, _ = make_worker(store, source, settings, FakeExtractor())

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)
    assert (job.status, job.attempts) == ("failed", 1)
    assert job.error_type == "cookies_expired"
    assert store.spend_rows == []  # failed before the paid call — nothing ledgered


async def test_validation_failure_is_terminal_and_spend_recorded(tmp_path: Path) -> None:
    """The model call SUCCEEDED (tokens spent, row written) but produced
    garbage — validation_failed, raw output never repaired."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = FakeExtractor(dishes=[{"garbage": True}])
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)
    assert job.status == "failed"
    assert job.error_type == "validation_failed"
    assert len(store.spend_rows) == 1
    assert store.recipes == []


async def test_extraction_failed_attempts_all_ledgered(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = FakeExtractor(failure=errors.ExtractionFailedError("non-JSON output"))
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    for _ in range(3):
        job = await claim_and_process(worker, store)
    assert (job.status, job.error_type) == ("failed", "extraction_failed")
    # Zero-token failure rows still count as attempts in the ledger:
    assert len(store.spend_rows) == 3
    assert all(row["tokens_in"] == 0 for row in store.spend_rows)
    assert all(row["model"] == "fake-extractor" for row in store.spend_rows)


@pytest.mark.parametrize(
    "make_failure",
    [
        lambda usage: errors.ExtractionFailedError("billed but unparseable", usage=usage),
        lambda usage: errors.RateLimitedError("throttled after billing", usage=usage),
    ],
)
async def test_failed_attempt_with_carried_usage_ledgers_real_tokens(
    tmp_path: Path, make_failure
) -> None:
    """The jobs-ADR known-limitation fix: when the adapter salvaged usage from
    the failing response, the ledger records REAL tokens — not zeros."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    carried = ExtractionUsage(
        model_id="gemini-test-model",
        prompt_version="v1",
        tokens_in=1200,
        tokens_out=340,
        tokens_thinking=0,
    )
    extractor = FakeExtractor(failure=make_failure(carried))
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "pending"  # retryable — requeued
    assert len(store.spend_rows) == 1
    row = store.spend_rows[0]
    assert row["tokens_in"] == 1200
    assert row["tokens_out"] == 340
    assert row["model"] == "gemini-test-model"  # the FAILING attempt's model, verbatim


async def test_failed_attempt_without_usage_still_ledgers_zeros(tmp_path: Path) -> None:
    """No carried usage (the pre-fix shape) keeps the zero-row contract:
    the row exists (daily cap counts rows) with zero tokens."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = FakeExtractor(failure=errors.ExtractionFailedError("died before usage"))
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    await claim_and_process(worker, store)

    assert len(store.spend_rows) == 1
    assert store.spend_rows[0]["tokens_in"] == 0
    assert store.spend_rows[0]["tokens_out"] == 0


async def test_untyped_exception_in_extract_stage_is_typed_terminal(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = FakeExtractor(failure=RuntimeError("SDK exploded"))
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)
    assert (job.status, job.error_type) == ("failed", "extraction_failed")
    assert "RuntimeError" in job.error_detail
    assert "SDK exploded" in job.error_detail
    # FAIL-CLOSED ledger: an untyped error out of extract() (transport error
    # mid-call, SDK bug) may still have reached the API and burned tokens —
    # the attempt MUST be ledgered so the daily cap counts it.
    assert len(store.spend_rows) == 1
    assert store.spend_rows[0]["tokens_in"] == 0


async def test_config_error_from_extractor_call_is_terminal_and_unledgered(
    tmp_path: Path,
) -> None:
    """The one deliberate no-ledger failure: the extractor raising ConfigError
    means the API REFUSED the call (auth rejected) before processing anything
    — terminal config_error, no attempt row (per the record_spend contract)."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = FakeExtractor(failure=errors.ConfigError("Gemini API rejected our credentials"))
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)
    assert (job.status, job.error_type) == ("failed", "config_error")
    assert store.spend_rows == []  # refused before the model ran — nothing ledgered
    assert store.budget_checks == 1  # but the gate DID run before the call


async def test_untyped_exception_in_download_stage_is_typed_terminal(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    source.fail_fetch(FileNotFoundError("ffmpeg output vanished"))
    worker, _ = make_worker(store, source, settings, FakeExtractor())

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)
    assert (job.status, job.error_type) == ("failed", "download_failed")
    assert "FileNotFoundError" in job.error_detail


async def test_download_timeout_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs_module, "DOWNLOAD_TIMEOUT_SECONDS", 0.01)

    class SlowSource(FakeSource):
        async def fetch(self, ref, dest_dir):
            await asyncio.sleep(5)
            raise AssertionError("unreachable")

    store = FakeJobStore()
    source = SlowSource(platform="bilibili", canonical_id="BVtest00001-p1")
    settings = make_settings(tmp_path)
    worker, _ = make_worker(store, source, settings, FakeExtractor())

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)
    assert (job.status, job.attempts) == ("pending", 1)  # retryable timeout


async def test_extract_timeout_writes_attempt_row_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs_module, "EXTRACT_TIMEOUT_SECONDS", 0.01)

    class HangingExtractor:
        def __init__(self) -> None:
            self.calls = 0

        async def extract(self, video_path, source_title, source_duration_seconds):
            self.calls += 1
            await asyncio.sleep(5)

    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = HangingExtractor()
    worker, _ = make_worker(store, source, settings, extractor)  # type: ignore[arg-type]

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)
    assert (job.status, job.attempts) == ("pending", 1)
    assert len(store.spend_rows) == 1  # tokens may have burned — attempt ledgered


# ─── atomic store: raced-duplicate adoption ──────────────────────────────────


async def test_store_unique_violation_adopts_raced_rows(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    store.fail_store_once = True  # simulate UNIQUE(platform,canonical,dish) firing
    extractor = FakeExtractor()
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    raced_ids = [r.id for r in store.recipes]
    assert job.result_recipe_ids == raced_ids  # adopted, not duplicated, not failed
    assert len(store.recipes) == 1
    assert len(store.spend_rows) == 1


class ConflictNoRowsStore(FakeJobStore):
    """store_results reports the UNIQUE violation but NO racer rows exist —
    the inconsistent-datastore shape (a non-dedupe IntegrityError)."""

    async def store_results(self, job, documents, *, extraction_meta):
        return None


async def test_store_conflict_with_no_recipes_is_terminal_first_attempt(
    tmp_path: Path,
) -> None:
    """A duplicate-key conflict with NO adoptable rows is deterministic:
    retrying would burn one real paid model call per attempt. Must be
    terminal on the FIRST attempt, never requeued."""
    store, source = ConflictNoRowsStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = FakeExtractor()
    worker, _ = make_worker(store, source, settings, extractor)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert (job.status, job.attempts) == ("failed", 1)  # NOT "pending"
    assert job.error_type == "extraction_failed"
    assert "inconsistent datastore" in job.error_detail
    assert len(extractor.calls) == 1  # exactly ONE paid call, no retry burn
    assert len(store.spend_rows) == 1


# ─── startup reconcile ───────────────────────────────────────────────────────


async def test_reconcile_flips_running_jobs_to_interrupted() -> None:
    store = FakeJobStore()
    running = [
        store.seed_job(status=status, canonical_id=f"BV{i}")
        for i, status in enumerate(("downloading", "extracting", "validating"))
    ]
    untouched_pending = store.seed_job(status="pending", canonical_id="BVp")
    untouched_stored = store.seed_job(status="stored", canonical_id="BVs")

    flipped = await store.reconcile_interrupted()
    assert flipped == 3
    for job in running:
        assert (job.status, job.error_type) == ("failed", "interrupted")
    assert untouched_pending.status == "pending"
    assert untouched_stored.status == "stored"


async def test_cancel_mid_extract_leaves_stage_for_reconcile(tmp_path: Path) -> None:
    """Kill-the-api-mid-job (CI flavor): cancellation must NOT mark the job
    failed/retryable — the next boot's reconcile owns it (interrupted,
    explicit human retry, no auto re-spend)."""

    class BlockingExtractor:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.calls = 0

        async def extract(self, video_path, source_title, source_duration_seconds):
            self.calls += 1
            self.started.set()
            await asyncio.Event().wait()  # blocks until cancelled

    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = BlockingExtractor()
    worker, _ = make_worker(store, source, settings, extractor)  # type: ignore[arg-type]

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await store.claim_next_job()
    task = asyncio.create_task(worker.process(job))
    await asyncio.wait_for(extractor.started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert job.status == "extracting"  # left in its running stage on purpose
    assert store.spend_rows == []  # the attempt never completed — no double spend

    assert await store.reconcile_interrupted() == 1
    assert (job.status, job.error_type) == ("failed", "interrupted")
    # And the worker does NOT pick it up again (failed is terminal):
    assert await store.claim_next_job() is None


class FlakyStore(FakeJobStore):
    """Simulates a db outage mid-job: the next ``failures`` store writes
    raise (set_status inside the stage machine, then mark_failed inside the
    worker's own error handler — the exact chain a postgres restart hits)."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures_left = failures

    def _maybe_fail(self) -> None:
        if self.failures_left > 0:
            self.failures_left -= 1
            raise RuntimeError("db connection lost")

    async def set_status(self, job_id, status):  # type: ignore[override]
        self._maybe_fail()
        await super().set_status(job_id, status)

    async def mark_failed(self, job_id, error_type, error_detail):  # type: ignore[override]
        self._maybe_fail()
        await super().mark_failed(job_id, error_type, error_detail)


class YieldingSleeper:
    """No-wall-clock sleeper that still yields to the event loop (run_forever
    would otherwise spin without ever letting the test observe progress)."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        await asyncio.sleep(0)


async def test_run_forever_survives_store_failure_mid_job(tmp_path: Path) -> None:
    """A db outage mid-job (set_status raises, then mark_failed raises inside
    the error handler) must NOT kill the worker task: the job is left
    mid-stage for reconcile and the NEXT job still gets processed."""
    store = FlakyStore(failures=2)  # set_status, then mark_failed
    source = make_source()
    settings = make_settings(tmp_path)
    extractor = FakeExtractor()
    worker = Worker(
        store=store,
        adapters=[source],
        settings=settings,
        extractor_factory=lambda _s: extractor,
        cover_generator=FakeCoverGenerator(),
        sleeper=YieldingSleeper(),
        jitter=lambda: 0.0,
    )

    job_one, _ = await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    source_two = make_source(canonical_id="BVtest00002-p1")
    job_two, _ = await enqueue_extract(
        store, OWNER_ID, "https://fake.example/video/2", [source_two], settings
    )

    task = asyncio.create_task(worker.run_forever())
    try:
        for _ in range(5000):
            if job_two.status == "stored":
                break
            await asyncio.sleep(0)
        assert not task.done(), (
            f"worker task died instead of surviving the store failure: {task}"
        )
        assert job_two.status == "stored"  # the queue kept moving
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # Job one was left mid-stage (NOT failed/requeued by a broken store) —
    # exactly what the next boot's reconcile owns:
    assert job_one.status == "downloading"
    assert await store.reconcile_interrupted() == 1
    assert (job_one.status, job_one.error_type) == ("failed", "interrupted")


# ─── politeness + media retention ────────────────────────────────────────────


async def test_politeness_delay_before_platform_fetch(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    worker, sleeper = make_worker(store, source, settings, FakeExtractor())

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    await claim_and_process(worker, store)

    assert len(sleeper.calls) == 1  # exactly one delay: before the fetch
    assert sleeper.calls[0] == pytest.approx(2.75)  # 2 + (5-2) * 0.25 jitter
    assert (
        jobs_module.POLITENESS_DELAY_MIN_SECONDS
        <= sleeper.calls[0]
        <= jobs_module.POLITENESS_DELAY_MAX_SECONDS
    )


async def test_media_retention_keep_moves_into_archive(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path, media_retention="keep")
    worker, _ = make_worker(store, source, settings, FakeExtractor())

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    archive_dir = tmp_path / "media" / "bilibili" / "BVtest00001-p1"
    archived = sorted(archive_dir.iterdir())
    videos = [path for path in archived if path.suffix == ".mp4"]
    assert len(videos) == 1
    assert archive_dir / "cover-0.jpg" in archived  # the cover stage wrote next to it
    meta = store.recipes[0].extraction_meta
    assert meta["retained_media"] == [str(videos[0])]  # covers are NOT retained media
    # Scratch is still cleaned even when media was retained:
    assert not (tmp_path / "scratch" / "chefclaw-jobs" / str(job.id)).exists()


# ─── covers (poster keyframes — strictly best-effort, post-store) ────────────


async def test_cover_happy_path_persists_cover_after_store(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path, media_retention="keep")
    covers = FakeCoverGenerator()
    worker, _ = make_worker(store, source, settings, FakeExtractor(), covers)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    archive_dir = tmp_path / "media" / "bilibili" / "BVtest00001-p1"
    assert store.recipes[0].cover_path == str(archive_dir / "cover-0.jpg")
    assert Path(store.recipes[0].cover_path).is_absolute()  # media root is resolve()d
    assert (archive_dir / "cover-0.jpg").is_file()
    # The frame came from the RETAINED archive file, never scratch:
    video_path, target_dir, frames = covers.calls[0]
    assert video_path.parent == archive_dir
    assert target_dir == archive_dir
    assert frames == [(0, pytest.approx(0.5))]  # single dish: (0+1)/(1+1)


async def test_discard_retention_never_writes_covers(tmp_path: Path) -> None:
    """media_retention=discard (the golden/CI stacks): no scratch-sourced
    covers, nothing persisted under media_dir — has_cover simply stays
    false."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)  # media_retention="discard"
    covers = FakeCoverGenerator()
    worker, _ = make_worker(store, source, settings, FakeExtractor(), covers)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    assert covers.calls == []  # the generator never ran
    assert store.recipes[0].cover_path is None
    media_dir = tmp_path / "media"
    assert not media_dir.exists() or not any(media_dir.rglob("*"))


@pytest.mark.parametrize(
    "cover_kwargs",
    [dict(fail=True), dict(error=RuntimeError("ffmpeg exploded"))],
)
async def test_cover_failure_still_stores_with_none(tmp_path: Path, cover_kwargs: dict) -> None:
    """A cover failure (per-dish None or the generator raising) must NEVER
    fail the job — the recipes are already stored when covers run."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path, media_retention="keep")
    worker, _ = make_worker(
        store, source, settings, FakeExtractor(), FakeCoverGenerator(**cover_kwargs)
    )

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    assert len(job.result_recipe_ids) == 1
    assert store.recipes[0].cover_path is None


async def test_cover_generator_hang_cannot_lose_the_paid_store(tmp_path: Path) -> None:
    """The paid-work crash-loss window fix: the atomic store commits BEFORE
    cover generation, so a wedged ffmpeg (slow/corrupt video) can no longer
    delay or lose paid extraction — a crash mid-covers is healed by the
    startup backfill."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path, media_retention="keep")
    covers = FakeCoverGenerator(hang=True)
    worker, _ = make_worker(store, source, settings, FakeExtractor(), covers)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await store.claim_next_job()
    assert job is not None
    task = asyncio.create_task(worker.process(job))
    for _ in range(5000):
        if job.status == "stored":
            break
        await asyncio.sleep(0)

    assert job.status == "stored"  # recipes landed while the generator hangs
    assert len(job.result_recipe_ids) == 1
    assert store.recipes[0].cover_path is None  # the backfill's job now
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_multi_dish_covers_distinct_paths_and_spread_fractions(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path, media_retention="keep")
    dish_two = default_dish()
    dish_two["dish_name"] = {"en": "Second dish", "original": "第二道菜"}
    covers = FakeCoverGenerator()
    worker, _ = make_worker(
        store, source, settings, FakeExtractor(dishes=[default_dish(), dish_two]), covers
    )

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    archive_dir = tmp_path / "media" / "bilibili" / "BVtest00001-p1"
    assert [r.cover_path for r in store.recipes] == [
        str(archive_dir / "cover-0.jpg"),
        str(archive_dir / "cover-1.jpg"),
    ]
    # Sibling covers spread across the video: dish i at (i+1)/(N+1).
    _, _, frames = covers.calls[0]
    assert frames == [(0, pytest.approx(1 / 3)), (1, pytest.approx(2 / 3))]


async def test_upload_job_cover_lands_under_local_platform(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path, media_retention="keep")
    video = tmp_path / "saved.mp4"
    video.write_bytes(b"uploaded video")
    await enqueue_upload(store, OWNER_ID, video, None, None, settings)

    covers = FakeCoverGenerator()
    worker, _ = make_worker(store, make_source(), settings, FakeExtractor(), covers)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    expected = tmp_path / "media" / "local" / job.canonical_id / "cover-0.jpg"
    assert store.recipes[0].cover_path == str(expected)


# ─── cover backfill (one-shot on worker startup, best-effort) ────────────────


async def test_backfill_generates_covers_from_archived_videos(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    recipe = store.seed_recipe(cover_path=None)
    archive_dir = tmp_path / "media" / "bilibili" / "BVfake000-p1"
    archive_dir.mkdir(parents=True)
    (archive_dir / "BVfake000.mp4").write_bytes(b"retained video")
    covers = FakeCoverGenerator()
    worker, _ = make_worker(store, make_source(), settings, FakeExtractor(), covers)

    await worker.backfill_covers()

    assert recipe.cover_path == str(archive_dir / "cover-0.jpg")
    video_path, _, frames = covers.calls[0]
    assert video_path == archive_dir / "BVfake000.mp4"
    assert frames == [(0, pytest.approx(0.5))]


async def test_backfill_partial_group_regenerates_only_missing_at_true_fractions(
    tmp_path: Path,
) -> None:
    """A partially-covered multi-dish group: fractions come from the group's
    TRUE dish count (covered siblings included, max(dish_index)+1 over ALL
    rows), only the MISSING dishes are requested, and existing sibling covers
    are never overwritten."""
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    archive_dir = tmp_path / "media" / "bilibili" / "BVfake000-p1"
    archive_dir.mkdir(parents=True)
    (archive_dir / "BVfake000.mp4").write_bytes(b"retained video")
    covered_zero = store.seed_recipe(dish_index=0, cover_path=str(archive_dir / "cover-0.jpg"))
    missing_one = store.seed_recipe(dish_index=1, cover_path=None)
    covered_two = store.seed_recipe(dish_index=2, cover_path=str(archive_dir / "cover-2.jpg"))
    covers = FakeCoverGenerator()
    worker, _ = make_worker(store, make_source(), settings, FakeExtractor(), covers)

    await worker.backfill_covers()

    # Only dish 1 was requested, at the 3-dish spread's (1+1)/(3+1) = 0.5 —
    # never a 1-dish 0.5-of-a-different-N by accident of the missing count:
    _, _, frames = covers.calls[0]
    assert frames == [(1, pytest.approx(2 / 4))]
    assert missing_one.cover_path == str(archive_dir / "cover-1.jpg")
    assert covered_zero.cover_path == str(archive_dir / "cover-0.jpg")  # untouched
    assert covered_two.cover_path == str(archive_dir / "cover-2.jpg")  # untouched


async def test_backfill_skips_recipes_without_an_archived_video(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    no_video = store.seed_recipe(cover_path=None)  # no media dir at all
    covered = store.seed_recipe(canonical_id="BVdone", cover_path="/data/media/x/cover-0.jpg")
    covers = FakeCoverGenerator()
    worker, _ = make_worker(store, make_source(), settings, FakeExtractor(), covers)

    await worker.backfill_covers()

    assert covers.calls == []  # nothing to generate from — and no crash
    assert no_video.cover_path is None
    assert covered.cover_path == "/data/media/x/cover-0.jpg"  # untouched


async def test_backfill_generator_failure_never_raises(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    recipe = store.seed_recipe(cover_path=None)
    archive_dir = tmp_path / "media" / "bilibili" / "BVfake000-p1"
    archive_dir.mkdir(parents=True)
    (archive_dir / "video.mp4").write_bytes(b"retained video")
    worker, _ = make_worker(
        store,
        make_source(),
        settings,
        FakeExtractor(),
        FakeCoverGenerator(error=RuntimeError("ffmpeg exploded")),
    )

    await worker.backfill_covers()  # best-effort: swallowed and logged

    assert recipe.cover_path is None


async def test_run_forever_backfills_once_when_enabled(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    recipe = store.seed_recipe(cover_path=None)
    archive_dir = tmp_path / "media" / "bilibili" / "BVfake000-p1"
    archive_dir.mkdir(parents=True)
    (archive_dir / "video.mp4").write_bytes(b"retained video")
    covers = FakeCoverGenerator()
    worker = Worker(
        store=store,
        adapters=[make_source()],
        settings=settings,
        extractor_factory=lambda _s: FakeExtractor(),
        cover_generator=covers,
        backfill_covers_on_start=True,
        sleeper=YieldingSleeper(),
        jitter=lambda: 0.0,
    )

    task = asyncio.create_task(worker.run_forever())
    try:
        for _ in range(5000):
            if recipe.cover_path is not None:
                break
            await asyncio.sleep(0)
        assert recipe.cover_path == str(archive_dir / "cover-0.jpg")
        assert len(covers.calls) == 1  # one-shot, not per idle loop
        assert worker.backfill_task is not None  # the handle is exposed
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_backfill_runs_in_background_without_delaying_job_claims(tmp_path: Path) -> None:
    """The one-shot backfill is a BACKGROUND task: a slow/wedged ffmpeg pass
    must never delay the first job claim. (Job execution stays strictly
    serial — the backfill only runs ffmpeg subprocesses + row updates.)"""
    store = FakeJobStore()
    settings = make_settings(tmp_path)  # discard: the live job never calls the generator
    stale = store.seed_recipe(cover_path=None, canonical_id="BVstale")
    archive_dir = tmp_path / "media" / "bilibili" / "BVstale"
    archive_dir.mkdir(parents=True)
    (archive_dir / "video.mp4").write_bytes(b"retained video")
    covers = FakeCoverGenerator(hang=True)  # the backfill wedges on its generator
    source = make_source()
    worker = Worker(
        store=store,
        adapters=[source],
        settings=settings,
        extractor_factory=lambda _s: FakeExtractor(),
        cover_generator=covers,
        backfill_covers_on_start=True,
        sleeper=YieldingSleeper(),
        jitter=lambda: 0.0,
    )
    job, _ = await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)

    task = asyncio.create_task(worker.run_forever())
    try:
        for _ in range(5000):
            if job.status == "stored":
                break
            await asyncio.sleep(0)
        assert job.status == "stored"  # claimed + processed while the backfill hangs
        assert worker.backfill_task is not None
        assert not worker.backfill_task.done()
        assert stale.cover_path is None
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    # Worker shutdown cancels the backfill with it:
    with pytest.raises(asyncio.CancelledError):
        await worker.backfill_task


async def test_run_forever_skips_backfill_by_default(tmp_path: Path) -> None:
    """The flag defaults OFF: a worker built without it never runs the
    backfill (unit-test posture; only the app lifespan turns it on)."""
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    recipe = store.seed_recipe(cover_path=None)
    covers = FakeCoverGenerator()
    worker = Worker(
        store=store,
        adapters=[make_source()],
        settings=settings,
        extractor_factory=lambda _s: FakeExtractor(),
        cover_generator=covers,
        sleeper=YieldingSleeper(),
        jitter=lambda: 0.0,
    )

    task = asyncio.create_task(worker.run_forever())
    try:
        for _ in range(200):
            await asyncio.sleep(0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert worker.backfill_task is None
    assert covers.calls == []
    assert recipe.cover_path is None


# ─── default_source_adapters (CHEFCLAW_SOURCES selection, §16.9) ─────────────


def test_default_source_adapters_real_registers_platform_adapters(tmp_path: Path) -> None:
    adapters = jobs_module.default_source_adapters(make_settings(tmp_path))
    assert [adapter.platform for adapter in adapters] == ["bilibili", "rednote"]


def test_default_source_adapters_fake_uses_real_platform_enum(tmp_path: Path) -> None:
    adapters = jobs_module.default_source_adapters(
        make_settings(tmp_path, chefclaw_sources="fake")
    )
    assert len(adapters) == 1
    fake = adapters[0]
    assert isinstance(fake, FakeSource)
    # platform must be a REAL enum value — document SourceInfo validation
    # would reject a stored dish whose provenance platform isn't one.
    assert fake.platform == "bilibili"
    assert fake.canonical_id == "fake-golden-1"
    assert fake.matches("fake://golden-check")
    assert not fake.matches("https://www.bilibili.com/video/BV1xx411c7mD")


def test_default_source_adapters_unknown_value_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(errors.ConfigError):
        jobs_module.default_source_adapters(make_settings(tmp_path, chefclaw_sources="prod"))
