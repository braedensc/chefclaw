"""Cost-guardrail tests (chefclaw.spend) — fail-closed parsing, conservative
cost math, the budget gate's order of operations, and ledger writes. No
database: the SQL-backed readers are monkeypatched where needed."""

import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from chefclaw import spend
from chefclaw.config import Settings
from chefclaw.errors import BudgetExceededError, ConfigError
from chefclaw.extractors import ExtractionUsage

OWNER_ID = uuid.uuid4()


def make_settings(monthly: str = "10", daily: str = "25") -> Settings:
    return Settings(
        monthly_llm_budget_usd=monthly,
        max_extraction_attempts_per_day=daily,
    )


def usage(model_id: str, tokens_in: int = 0, tokens_out: int = 0, thinking: int = 0):
    return ExtractionUsage(
        model_id=model_id,
        prompt_version="v1",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_thinking=thinking,
    )


# ── parse_budget: fail-closed (§16.8) ────────────────────────────────────────


def test_parse_budget_valid() -> None:
    assert spend.parse_budget(make_settings("10", "25")) == (Decimal("10"), 25)
    assert spend.parse_budget(make_settings("7.50", "1")) == (Decimal("7.50"), 1)


@pytest.mark.parametrize("monthly", ["", "  ", "ten dollars", "$10", "0", "-3", "nan", "inf"])
def test_parse_budget_bad_monthly_fails_closed(monthly: str) -> None:
    with pytest.raises(ConfigError, match="MONTHLY_LLM_BUDGET_USD"):
        spend.parse_budget(make_settings(monthly=monthly))


@pytest.mark.parametrize("daily", ["", "  ", "many", "2.5", "0", "-1"])
def test_parse_budget_bad_daily_fails_closed(daily: str) -> None:
    with pytest.raises(ConfigError, match="MAX_EXTRACTION_ATTEMPTS_PER_DAY"):
        spend.parse_budget(make_settings(daily=daily))


# ── estimate_cost: conservative arithmetic ───────────────────────────────────


def test_estimate_cost_known_model_exact() -> None:
    # flash: 0.60 in / 5.00 out per 1M (padded table values)
    cost = spend.estimate_cost(usage("gemini-2.5-flash", tokens_in=1_000_000, tokens_out=100_000))
    assert cost == Decimal("1.10")


def test_estimate_cost_thinking_billed_as_output() -> None:
    with_thinking = spend.estimate_cost(
        usage("gemini-2.5-flash", tokens_out=100_000, thinking=100_000)
    )
    without = spend.estimate_cost(usage("gemini-2.5-flash", tokens_out=200_000))
    assert with_thinking == without


def test_estimate_cost_longest_prefix_wins() -> None:
    # "gemini-2.5-flash-lite-001" must price as flash-LITE, not flash.
    lite = spend.estimate_cost(usage("gemini-2.5-flash-lite-001", tokens_in=1_000_000))
    assert lite == Decimal("0.40")


def test_estimate_cost_unknown_model_uses_most_expensive_rates() -> None:
    unknown = spend.estimate_cost(usage("gemini-9.9-mystery", tokens_in=1_000_000))
    pro = spend.estimate_cost(usage("gemini-2.5-pro", tokens_in=1_000_000))
    assert unknown == pro  # conservative: never silently cheap


def test_estimate_cost_rounds_up_at_the_quantum() -> None:
    # 1 input token on flash = $0.0000006 — rounds UP to the 6-place quantum.
    assert spend.estimate_cost(usage("gemini-2.5-flash", tokens_in=1)) == Decimal("0.000001")


def test_estimate_cost_fake_extractor_is_free() -> None:
    assert spend.estimate_cost(usage("fake-extractor", tokens_in=10_000, tokens_out=10_000)) == 0


# ── UTC windows ──────────────────────────────────────────────────────────────


def test_month_and_day_start_are_utc_windows() -> None:
    # 03:30+05:00 on July 1 is still June 30 in UTC — windows must follow UTC.
    local = datetime(2026, 7, 1, 3, 30, tzinfo=timezone(timedelta(hours=5)))
    assert spend.month_start(local) == datetime(2026, 6, 1, tzinfo=UTC)
    assert spend.day_start(local) == datetime(2026, 6, 30, tzinfo=UTC)


# ── check_budget: the gate ───────────────────────────────────────────────────


def _patch_ledger(
    monkeypatch: pytest.MonkeyPatch, *, spent: Decimal, attempts: int
) -> dict[str, int]:
    calls = {"month": 0, "day": 0}

    async def fake_month(session, owner_id):
        calls["month"] += 1
        return spent

    async def fake_day(session, owner_id):
        calls["day"] += 1
        return attempts

    monkeypatch.setattr(spend, "month_to_date_usd", fake_month)
    monkeypatch.setattr(spend, "attempts_today", fake_day)
    return calls


async def test_check_budget_passes_under_both_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ledger(monkeypatch, spent=Decimal("1.00"), attempts=3)
    await spend.check_budget(None, make_settings("10", "25"), OWNER_ID)


async def test_check_budget_monthly_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ledger(monkeypatch, spent=Decimal("10.00"), attempts=0)
    with pytest.raises(BudgetExceededError, match="monthly"):
        await spend.check_budget(None, make_settings("10", "25"), OWNER_ID)


async def test_check_budget_daily_cap_with_attempts_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ledger(monkeypatch, spent=Decimal("0.50"), attempts=25)
    with pytest.raises(BudgetExceededError, match="25 attempts"):
        await spend.check_budget(None, make_settings("10", "25"), OWNER_ID)


async def test_check_budget_config_error_before_any_ledger_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed ORDER: unusable config refuses before touching the DB."""
    calls = _patch_ledger(monkeypatch, spent=Decimal("0"), attempts=0)
    with pytest.raises(ConfigError):
        await spend.check_budget(None, make_settings(monthly=""), OWNER_ID)
    assert calls == {"month": 0, "day": 0}


# ── record_spend ─────────────────────────────────────────────────────────────


class _FakeSession:
    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    def add(self, row) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1


async def test_record_spend_writes_and_commits_one_row() -> None:
    session = _FakeSession()
    job_id = uuid.uuid4()
    row = await spend.record_spend(
        session,
        job_id=job_id,
        owner_id=OWNER_ID,
        usage=usage("gemini-2.5-flash", tokens_in=100, tokens_out=50, thinking=7),
        cost_usd=Decimal("0.000123"),
    )
    assert session.added == [row]
    assert session.commits == 1
    assert row.job_id == job_id
    assert row.owner_id == OWNER_ID
    assert row.model == "gemini-2.5-flash"
    assert (row.tokens_in, row.tokens_out, row.tokens_thinking) == (100, 50, 7)
    assert row.cost_usd == Decimal("0.000123")


async def test_record_spend_zero_token_failure_row_is_legal() -> None:
    """A failed attempt with unknown token counts still writes a row — the
    row itself is what the daily attempt cap counts."""
    session = _FakeSession()
    row = await spend.record_spend(
        session,
        job_id=uuid.uuid4(),
        owner_id=OWNER_ID,
        usage=usage("gemini-2.5-flash"),
        cost_usd=Decimal("0"),
    )
    assert session.commits == 1
    assert (row.tokens_in, row.tokens_out, row.tokens_thinking) == (0, 0, 0)


# ── budget alerting (V2-A ADR — crossing-edge) ───────────────────────────────


def test_thresholds_crossed_edges() -> None:
    budget = Decimal("10")
    crossed = spend.thresholds_crossed
    assert crossed(Decimal("7.90"), Decimal("8.00"), budget) == [80]
    assert crossed(Decimal("9.99"), Decimal("10.00"), budget) == [100]
    # One big attempt can cross both thresholds at once.
    assert crossed(Decimal("7.00"), Decimal("10.50"), budget) == [80, 100]
    # Already past the line before this attempt => no re-alert.
    assert crossed(Decimal("8.00"), Decimal("9.00"), budget) == []
    assert crossed(Decimal("10.00"), Decimal("11.00"), budget) == []
    # Below every line: silence.
    assert crossed(Decimal("0"), Decimal("7.99"), budget) == []


async def test_alert_budget_progress_logs_and_captures(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def fake_month(session, owner_id):
        return Decimal("8.10")  # after this attempt's 0.20: before was 7.90

    captured: list[tuple[str, int]] = []
    monkeypatch.setattr(spend, "month_to_date_usd", fake_month)
    monkeypatch.setattr(
        spend.observability, "capture_budget_alert", lambda msg, pct: captured.append((msg, pct))
    )

    import logging

    with caplog.at_level(logging.WARNING, logger="chefclaw.spend"):
        await spend.alert_budget_progress(None, make_settings(), OWNER_ID, Decimal("0.20"))

    (record,) = [r for r in caplog.records if r.name == "chefclaw.spend"]
    assert record.budget_pct == 80
    ((message, pct),) = captured
    assert pct == 80
    assert "80%" in message


async def test_alert_budget_progress_failclosed_config_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed budget config => no paid calls happen, so alerting simply
    returns (and must not raise out of the ledger write path)."""
    reads = {"month": 0}

    async def fake_month(session, owner_id):
        reads["month"] += 1
        return Decimal("0")

    monkeypatch.setattr(spend, "month_to_date_usd", fake_month)
    await spend.alert_budget_progress(None, Settings(), OWNER_ID, Decimal("0.20"))
    assert reads["month"] == 0  # config parse failed first; no ledger read


async def test_alert_budget_progress_never_raises_on_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_month(session, owner_id):
        raise RuntimeError("db went away")

    monkeypatch.setattr(spend, "month_to_date_usd", broken_month)
    # Must swallow: alerting is best-effort and follows a COMMITTED write.
    await spend.alert_budget_progress(None, make_settings(), OWNER_ID, Decimal("0.20"))
