"""Observability tests (V2-A ADR).

The acceptance claims proven here, adversarially where possible:
- DSN absent ⇒ ``sentry_sdk.init`` is NEVER called (spied, not assumed) and
  every capture helper is safe to call uninitialised.
- DSN present ⇒ init happens with environment/release tags and tracing off.
- A job failing terminally produces exactly ONE event tagged with
  job_id + stage + error_type + platform (captured via ``before_send``
  returning None — nothing is ever sent anywhere, even in this test).
- The request middleware logs /api/* with method/path/status/latency/owner,
  demotes /api/health to DEBUG, and ignores non-API paths.
"""

import json
import logging
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import sentry_sdk
from httpx import AsyncClient

from chefclaw import errors, observability
from chefclaw.config import Settings
from chefclaw.extractors.fake import FakeExtractor
from chefclaw.observability import JsonFormatter
from chefclaw.services.jobs import enqueue_extract
from tests.conftest import OWNER_ID, TEST_TOKEN, bearer
from tests.fakes import FakeJobStore
from tests.test_worker import (
    FAKE_URL,
    claim_and_process,
    make_settings,
    make_source,
    make_worker,
)


@pytest.fixture(autouse=True)
def sentry_flag_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module 'sentry is on' flag around every test (monkeypatch
    restores the original after, even when a test flips it via init)."""
    monkeypatch.setattr(observability, "_sentry_enabled", False)


# ─── JSON formatter ──────────────────────────────────────────────────────────


def _record(msg: str, **extra: object) -> logging.LogRecord:
    return logging.getLogger("chefclaw.test").makeRecord(
        "chefclaw.test", logging.INFO, __file__, 1, msg, (), None, extra=extra
    )


def test_json_formatter_shape_and_extras() -> None:
    payload = json.loads(JsonFormatter().format(_record("hello", job_id="j1", duration_ms=1.5)))
    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "chefclaw.test"
    assert payload["job_id"] == "j1"
    assert payload["duration_ms"] == 1.5
    assert "ts" in payload


def test_json_formatter_stringifies_non_json_types() -> None:
    """UUIDs/Decimals in extras must not crash the formatter — a log line
    that raises is an outage amplifier."""
    some_uuid = uuid.uuid4()
    payload = json.loads(
        JsonFormatter().format(_record("x", owner=some_uuid, cost=Decimal("0.5")))
    )
    assert payload["owner"] == str(some_uuid)
    assert payload["cost"] == "0.5"


def test_json_formatter_includes_exception_text() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.getLogger("chefclaw.test").makeRecord(
            "chefclaw.test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exc"]


# ─── Sentry gating (the DSN-absent proof) ────────────────────────────────────


def test_no_dsn_never_touches_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(observability.sentry_sdk, "init", lambda **kw: calls.append(kw))
    assert observability.init_sentry(Settings()) is False
    assert calls == []
    assert observability.sentry_enabled() is False


def test_dsn_initialises_with_tags_and_tracing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(observability.sentry_sdk, "init", lambda **kw: calls.append(kw))
    settings = Settings(
        sentry_dsn="https://examplekey@o0.ingest.example.test/1",
        sentry_environment="vps",
        sentry_release="abc1234",
    )
    assert observability.init_sentry(settings) is True
    assert observability.sentry_enabled() is True
    (kwargs,) = calls
    assert kwargs["dsn"] == "https://examplekey@o0.ingest.example.test/1"
    assert kwargs["environment"] == "vps"
    assert kwargs["release"] == "abc1234"
    assert kwargs["traces_sample_rate"] == 0.0
    assert kwargs["send_default_pii"] is False


def test_capture_helpers_are_safe_uninitialised() -> None:
    """The worker calls these unconditionally — with no DSN they must no-op,
    never raise (a crash in error REPORTING failing the job would be absurd)."""
    observability.capture_job_failure(
        ValueError("x"),
        job_id=uuid.uuid4(),
        stage="extract",
        error_type="extraction_failed",
        platform="bilibili",
        attempt=1,
    )
    observability.add_job_breadcrumb("requeued", job_id=uuid.uuid4(), stage="download")
    observability.capture_budget_alert("80% reached", 80)


# ─── Worker terminal failure → tagged event ──────────────────────────────────


@pytest.fixture
def sentry_events() -> list[dict]:
    """Real SDK, zero network: ``before_send`` collects the event and returns
    None, which DROPS it before any transport touch. Teardown swaps in a
    disabled (DSN-less) client so no other test sees an initialised SDK."""
    events: list[dict] = []

    def collect_and_drop(event: dict, hint: dict) -> None:
        events.append(event)
        return None

    sentry_sdk.init(
        dsn="https://0123456789abcdef0123456789abcdef@o0.ingest.example.invalid/1",
        before_send=collect_and_drop,
        default_integrations=False,
        traces_sample_rate=0.0,
        shutdown_timeout=0,
    )
    yield events
    sentry_sdk.init(dsn=None, default_integrations=False, shutdown_timeout=0)


async def test_terminal_job_failure_is_one_tagged_event(
    tmp_path: Path, sentry_events: list[dict]
) -> None:
    """THE acceptance test: a job dying in the extract stage produces a
    Sentry issue carrying job id + stage + error_type (v2 plan V2-A)."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    # ValidationFailedError is non-retryable => terminal on the first attempt.
    extractor = FakeExtractor(failure=errors.ValidationFailedError("model output invalid"))
    worker, _ = make_worker(store, source, settings, extractor)
    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)

    job = await claim_and_process(worker, store)

    assert job.status == "failed"
    (event,) = sentry_events
    assert event["tags"]["job_id"] == str(job.id)
    assert event["tags"]["stage"] == "extract"
    assert event["tags"]["error_type"] == "validation_failed"
    assert event["tags"]["platform"] == "bilibili"


async def test_retryable_requeue_emits_no_event(
    tmp_path: Path, sentry_events: list[dict]
) -> None:
    """Retries are breadcrumbs, not issues — only the terminal failure pages."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path)
    extractor = FakeExtractor(failure=errors.ExtractionFailedError("transient"))
    worker, _ = make_worker(store, source, settings, extractor)
    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)

    job = await claim_and_process(worker, store)  # attempt 1 of MAX 3 => requeue

    assert job.status == "pending"
    assert sentry_events == []


# ─── Request-log middleware ──────────────────────────────────────────────────


def _request_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "chefclaw.request"]


async def test_api_requests_get_one_info_line(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="chefclaw.request"):
        response = await client.get("/api/jobs/not-a-uuid", headers=bearer(TEST_TOKEN))
    assert response.status_code == 422
    (record,) = _request_records(caplog)
    assert record.levelno == logging.INFO
    assert record.http_method == "GET"
    assert record.http_path == "/api/jobs/not-a-uuid"
    assert record.http_status == 422
    assert record.duration_ms >= 0
    assert record.owner_id == str(OWNER_ID)  # resolved by require_owner


async def test_health_polls_log_at_debug_only(
    client: AsyncClient, ping_ok: None, caplog: pytest.LogCaptureFixture
) -> None:
    """The Settings screen polls /api/health every 15 s — that must not
    produce an INFO line per poll."""
    with caplog.at_level(logging.DEBUG, logger="chefclaw.request"):
        response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    (record,) = _request_records(caplog)
    assert record.levelno == logging.DEBUG
    assert record.http_path == "/api/health"


async def test_unauthenticated_request_logs_without_owner(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="chefclaw.request"):
        response = await client.get("/api/jobs")
    assert response.status_code == 401
    (record,) = _request_records(caplog)
    assert record.http_status == 401
    assert record.owner_id is None


async def test_non_api_paths_are_not_request_logged(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="chefclaw.request"):
        await client.get("/definitely-not-api")
    assert _request_records(caplog) == []
