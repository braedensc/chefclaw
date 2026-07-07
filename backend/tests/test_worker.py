"""Worker + enqueue tests — CI tier: no network, no database.

The persistence seam (tests/fakes.FakeJobStore) stands in for postgres; the
config-selectable FakeSource/FakeExtractor drive every taxonomy path. The
real store's SQL (SKIP LOCKED claim, atomic store, IntegrityError adopt) is
exercised by the golden DB tier (test_worker_db.py, `-m golden`).
"""

import asyncio
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from chefclaw import errors
from chefclaw.config import Settings
from chefclaw.extractors import ExtractionUsage
from chefclaw.extractors.fake import FakeExtractor, default_dish
from chefclaw.images import ImageResult
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


class FakeImageGenerator:
    """Injectable ImageGeneratorAdapter: returns placeholder image bytes
    without any network/spend (CI tier). Records the prompts it was handed
    (Hard Rule 7 assertions); ``error`` raises on generate; ``hang`` blocks
    forever (store-before-image / backfill tests)."""

    def __init__(
        self,
        error: Exception | None = None,
        hang: bool = False,
        cost_usd: Decimal = Decimal("0.067"),
        image_bytes: bytes = b"\xff\xd8fake jpeg bytes",
    ) -> None:
        self.error = error
        self.hang = hang
        self.cost_usd = cost_usd
        self.image_bytes = image_bytes
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> ImageResult:
        self.calls.append(prompt)
        if self.hang:
            await asyncio.Event().wait()  # blocks until cancelled
        if self.error is not None:
            raise self.error
        return ImageResult(
            image_bytes=self.image_bytes,
            model_id="fake-image",
            cost_usd=self.cost_usd,
        )


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
    image_generator: FakeImageGenerator | None = None,
) -> tuple[Worker, RecordingSleeper]:
    sleeper = RecordingSleeper()
    generator = image_generator or FakeImageGenerator()
    worker = Worker(
        store=store,
        adapters=[source],
        settings=settings,
        extractor_factory=lambda _settings: extractor,
        # never a real image API in CI:
        image_generator_factory=lambda _settings: generator,
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
    assert meta["prompt_version"] == "v3"
    assert meta["tokens"] == {"in": 1000, "out": 250, "thinking": 0}
    assert "extracted_at" in meta and "media_resolution" in meta
    # Derived estimates land in the SEPARATE column, never in the document:
    assert store.recipes[0].estimated == {
        "spiciness_level": 1,
        "difficulty_level": 1,
        "source": "derived",
    }
    assert "estimated" not in store.recipes[0].document
    # Auto-tags seed the editable tags column for every dish:
    assert store.recipes[0].tags == ["braise", "pork", "classic"]
    assert store.recipes[1].tags == ["braise", "pork", "classic"]
    # Ledger rows: one extraction attempt + one illustration per dish (2).
    extraction_rows = [r for r in store.spend_rows if r["model"] == "fake-extractor"]
    image_rows = [r for r in store.spend_rows if r["model"] == "fake-image"]
    assert len(extraction_rows) == 1
    assert extraction_rows[0]["tokens_in"] == 1000
    assert len(image_rows) == 2  # one per dish (discard-agnostic)
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
    # only the successful attempt reached the model (+ its illustration row):
    extraction_rows = [r for r in store.spend_rows if r["model"] == "fake-extractor"]
    assert len(extraction_rows) == 1


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

    async def store_results(self, job, documents, estimates, tags, *, extraction_meta):
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
        image_generator_factory=lambda _s: FakeImageGenerator(),
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
    # The illustration stage wrote next to the retained video (it does NOT
    # depend on retention — it would land here even with discard):
    assert archive_dir / "illustration-0.jpg" in archived
    meta = store.recipes[0].extraction_meta
    assert meta["retained_media"] == [str(videos[0])]  # illustrations are NOT retained media
    # Scratch is still cleaned even when media was retained:
    assert not (tmp_path / "scratch" / "chefclaw-jobs" / str(job.id)).exists()


# ─── illustrations (generated cartoon covers — best-effort, post-store) ──────


async def test_illustration_happy_path_persists_image_after_store(tmp_path: Path) -> None:
    """The illustration stage runs AFTER the atomic store, writes bytes to
    illustration-<dish_index>.jpg, sets image_url + style_version, and ledgers
    a spend row with the image model + its flat cost. It does NOT depend on
    media_retention (default discard here)."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)  # media_retention="discard"
    images = FakeImageGenerator()
    worker, _ = make_worker(store, source, settings, FakeExtractor(), images)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    archive_dir = tmp_path / "media" / "bilibili" / "BVtest00001-p1"
    expected = archive_dir / "illustration-0.jpg"
    assert store.recipes[0].image_url == str(expected)
    assert store.recipes[0].image_style_version == "cartoon-v1"
    assert Path(store.recipes[0].image_url).is_absolute()  # media root is resolve()d
    assert expected.is_file()
    # The paid image attempt was ledgered with the image model + flat cost:
    image_rows = [r for r in store.spend_rows if r["model"] == "fake-image"]
    assert len(image_rows) == 1
    assert image_rows[0]["cost_usd"] == Decimal("0.067")
    assert image_rows[0]["tokens_in"] == 0  # flat-billed, not token-based


async def test_illustration_prompt_is_text_only_never_quantities(tmp_path: Path) -> None:
    """Hard Rule 7: the prompt is built from text fields (dish name, ingredient
    NAMES) — NEVER a verbatim quantity like "500克"/"两大勺", never a frame."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    images = FakeImageGenerator()
    worker, _ = make_worker(store, source, settings, FakeExtractor(), images)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    await claim_and_process(worker, store)

    assert len(images.calls) == 1
    prompt = images.calls[0]
    assert "Red-braised pork belly" in prompt  # dish name (en)
    assert "pork belly" in prompt  # an ingredient NAME
    assert "cartoon" in prompt.lower()  # the style block is present
    # No verbatim quantity raw_text ever reaches the image model:
    assert "500克" not in prompt
    assert "两大勺" not in prompt
    assert "适量" not in prompt


async def test_illustration_generator_failure_still_stores_with_none(tmp_path: Path) -> None:
    """An image-API error must NEVER fail the job — the recipe is already
    stored when the illustration stage runs; image_url just stays NULL."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    images = FakeImageGenerator(error=RuntimeError("image API exploded"))
    worker, _ = make_worker(store, source, settings, FakeExtractor(), images)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    assert len(job.result_recipe_ids) == 1
    assert store.recipes[0].image_url is None
    # The generator failing before returning ⇒ no image spend row:
    assert [r for r in store.spend_rows if r["model"] == "fake-image"] == []


async def test_illustration_budget_exceeded_skips_and_still_stores(tmp_path: Path) -> None:
    """The illustration stage is budget-gated: check_budget raising (monthly
    budget / daily cap) must skip the image, leave image_url NULL, and NEVER
    fail the recipe store. The extraction budget check passed first (recipes
    exist), so this is the illustration-stage gate refusing the image call."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    images = FakeImageGenerator()
    worker, _ = make_worker(store, source, settings, FakeExtractor(), images)

    # Let extraction's budget check pass, then refuse the illustration's check.
    class OneAllowedStore(FakeJobStore):
        async def check_budget(self, owner_id):
            self.budget_checks += 1
            if self.budget_checks >= 2:  # 1 = extraction, 2 = illustration
                raise errors.BudgetExceededError("monthly LLM budget reached")

    store = OneAllowedStore()
    worker, _ = make_worker(store, source, settings, FakeExtractor(), images)

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    assert store.recipes[0].image_url is None
    assert images.calls == []  # the paid image call never happened
    assert [r for r in store.spend_rows if r["model"] == "fake-image"] == []


async def test_estimated_fields_land_on_the_recipe(tmp_path: Path) -> None:
    """The fake extractor's _DEFAULT_DISH carries an `estimated` block; it is
    split out into the separate `estimated` column (never the document)."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    worker, _ = make_worker(store, source, settings, FakeExtractor())

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    await claim_and_process(worker, store)

    assert store.recipes[0].estimated == {
        "spiciness_level": 1,
        "difficulty_level": 1,
        "source": "derived",
    }
    assert "estimated" not in store.recipes[0].document


async def test_auto_tags_seed_the_editable_tags_column(tmp_path: Path) -> None:
    """The fake extractor's _DEFAULT_DISH carries a `tags` list; it seeds the
    user-editable recipes.tags column as a smart default (never the document)."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    worker, _ = make_worker(store, source, settings, FakeExtractor())

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    await claim_and_process(worker, store)

    assert store.recipes[0].tags == ["braise", "pork", "classic"]
    assert "tags" not in store.recipes[0].document


async def test_dish_without_tags_stores_empty_list(tmp_path: Path) -> None:
    """A dish with no `tags` key stores an empty list — tags are an optional
    smart default, absent is fine (never fails the extraction)."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    untagged = default_dish()
    del untagged["tags"]
    worker, _ = make_worker(store, source, settings, FakeExtractor(dishes=[untagged]))

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    await claim_and_process(worker, store)

    assert store.recipes[0].tags == []


async def test_illustration_hang_cannot_lose_the_paid_store(tmp_path: Path) -> None:
    """The paid-work crash-loss window fix: the atomic store commits BEFORE the
    illustration stage, so a wedged image API can no longer delay or lose paid
    extraction — a crash mid-illustration is healed by the startup backfill."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    images = FakeImageGenerator(hang=True)
    worker, _ = make_worker(store, source, settings, FakeExtractor(), images)

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
    assert store.recipes[0].image_url is None  # the backfill's job now
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_multi_dish_illustrations_distinct_paths(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    dish_two = default_dish()
    dish_two["dish_name"] = {"en": "Second dish", "original": "第二道菜"}
    images = FakeImageGenerator()
    worker, _ = make_worker(
        store, source, settings, FakeExtractor(dishes=[default_dish(), dish_two]), images
    )

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    archive_dir = tmp_path / "media" / "bilibili" / "BVtest00001-p1"
    assert [r.image_url for r in store.recipes] == [
        str(archive_dir / "illustration-0.jpg"),
        str(archive_dir / "illustration-1.jpg"),
    ]
    assert len(images.calls) == 2  # one prompt per dish
    # Two image spend rows (one per dish):
    assert len([r for r in store.spend_rows if r["model"] == "fake-image"]) == 2


async def test_upload_job_illustration_lands_under_local_platform(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    video = tmp_path / "saved.mp4"
    video.write_bytes(b"uploaded video")
    await enqueue_upload(store, OWNER_ID, video, None, None, settings)

    images = FakeImageGenerator()
    worker, _ = make_worker(store, make_source(), settings, FakeExtractor(), images)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    expected = tmp_path / "media" / "local" / job.canonical_id / "illustration-0.jpg"
    assert store.recipes[0].image_url == str(expected)


# ─── illustration backfill (one-shot on worker startup, best-effort) ─────────


def _seed_recipe_with_job(store: FakeJobStore, **overrides):
    """Seed a stored recipe AND the stored job that lists it (the illustration
    backfill's inner join to result_recipe_ids needs a locatable job)."""
    recipe = store.seed_recipe(**overrides)
    store.seed_job(
        owner_id=recipe.owner_id,
        status="stored",
        platform=recipe.platform,
        canonical_id=recipe.canonical_id,
        result_recipe_ids=[recipe.id],
    )
    return recipe


async def test_backfill_generates_illustrations_for_missing_images(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    recipe = _seed_recipe_with_job(store, image_url=None, document=default_dish())
    images = FakeImageGenerator()
    worker, _ = make_worker(store, make_source(), settings, FakeExtractor(), images)

    await worker.backfill_illustrations()

    expected = tmp_path / "media" / "bilibili" / "BVfake000-p1" / "illustration-0.jpg"
    assert recipe.image_url == str(expected)
    assert recipe.image_style_version == "cartoon-v1"
    assert len(images.calls) == 1
    # The backfill's paid image attempt was ledgered too:
    assert len([r for r in store.spend_rows if r["model"] == "fake-image"]) == 1


async def test_backfill_skips_recipes_with_no_locatable_job(tmp_path: Path) -> None:
    """A recipe with no stored job (inner join on result_recipe_ids) is skipped
    — the illustration spend row needs a valid job FK to attribute to."""
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    orphan = store.seed_recipe(image_url=None, document=default_dish())  # no job seeded
    images = FakeImageGenerator()
    worker, _ = make_worker(store, make_source(), settings, FakeExtractor(), images)

    await worker.backfill_illustrations()

    assert images.calls == []  # nothing to attribute — and no crash
    assert orphan.image_url is None


async def test_backfill_leaves_already_imaged_recipes_untouched(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    done = _seed_recipe_with_job(
        store, canonical_id="BVdone", image_url="/data/media/x/illustration-0.jpg"
    )
    images = FakeImageGenerator()
    worker, _ = make_worker(store, make_source(), settings, FakeExtractor(), images)

    await worker.backfill_illustrations()

    assert images.calls == []  # image_url already set — nothing to do
    assert done.image_url == "/data/media/x/illustration-0.jpg"  # untouched


async def test_backfill_generator_failure_never_raises(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    recipe = _seed_recipe_with_job(store, image_url=None, document=default_dish())
    worker, _ = make_worker(
        store,
        make_source(),
        settings,
        FakeExtractor(),
        FakeImageGenerator(error=RuntimeError("image API exploded")),
    )

    await worker.backfill_illustrations()  # best-effort: swallowed and logged

    assert recipe.image_url is None


async def test_run_forever_backfills_once_when_enabled(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    recipe = _seed_recipe_with_job(store, image_url=None, document=default_dish())
    images = FakeImageGenerator()
    worker = Worker(
        store=store,
        adapters=[make_source()],
        settings=settings,
        extractor_factory=lambda _s: FakeExtractor(),
        image_generator_factory=lambda _s: images,
        backfill_illustrations_on_start=True,
        sleeper=YieldingSleeper(),
        jitter=lambda: 0.0,
    )

    task = asyncio.create_task(worker.run_forever())
    try:
        for _ in range(5000):
            if recipe.image_url is not None:
                break
            await asyncio.sleep(0)
        expected = tmp_path / "media" / "bilibili" / "BVfake000-p1" / "illustration-0.jpg"
        assert recipe.image_url == str(expected)
        assert len(images.calls) == 1  # one-shot, not per idle loop
        assert worker.backfill_task is not None  # the handle is exposed
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_backfill_runs_in_background_without_delaying_job_claims(tmp_path: Path) -> None:
    """The one-shot backfill is a BACKGROUND task: a slow/wedged image pass
    must never delay the first job claim. (Job execution stays strictly
    serial — the backfill only runs subprocess/HTTP + row updates.)"""
    store = FakeJobStore()
    settings = make_settings(tmp_path)
    stale = _seed_recipe_with_job(
        store, image_url=None, canonical_id="BVstale", document=default_dish()
    )
    # The live job's generator is separate from the wedged backfill generator:
    live_images = FakeImageGenerator()
    backfill_images = FakeImageGenerator(hang=True)
    generators = iter([backfill_images, live_images])
    source = make_source()
    worker = Worker(
        store=store,
        adapters=[source],
        settings=settings,
        extractor_factory=lambda _s: FakeExtractor(),
        image_generator_factory=lambda _s: next(generators),
        backfill_illustrations_on_start=True,
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
        assert stale.image_url is None
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
    recipe = _seed_recipe_with_job(store, image_url=None, document=default_dish())
    images = FakeImageGenerator()
    worker = Worker(
        store=store,
        adapters=[make_source()],
        settings=settings,
        extractor_factory=lambda _s: FakeExtractor(),
        image_generator_factory=lambda _s: images,
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
    assert images.calls == []
    assert recipe.image_url is None


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
