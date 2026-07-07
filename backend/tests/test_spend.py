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
    monkeypatch: pytest.MonkeyPatch,
    *,
    spent: Decimal,
    attempts: int,
    user_monthly: Decimal | None = None,
    user_daily: int | None = None,
) -> dict[str, int]:
    """Patch the gate's three DB reads (no session needed). ``user_monthly`` /
    ``user_daily`` default to None (no per-user override — the global env cap
    applies)."""
    calls = {"month": 0, "day": 0, "caps": 0}

    async def fake_month(session, owner_id):
        calls["month"] += 1
        return spent

    async def fake_day(session, owner_id):
        calls["day"] += 1
        return attempts

    async def fake_caps(session, owner_id):
        calls["caps"] += 1
        return user_monthly, user_daily

    monkeypatch.setattr(spend, "month_to_date_usd", fake_month)
    monkeypatch.setattr(spend, "attempts_today", fake_day)
    monkeypatch.setattr(spend, "read_user_caps", fake_caps)
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
    # Fail-closed config refuses before touching ANY read (caps included) — a
    # per-user cap can never re-enable spend the operator hasn't globally set.
    assert calls == {"month": 0, "day": 0, "caps": 0}


# ── check_budget: per-user caps override the global (M3) ─────────────────────


async def test_per_user_monthly_override_tighter_than_global_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-user monthly cap BELOW the global blocks at the lower line even
    though the global (10) would allow it."""
    _patch_ledger(monkeypatch, spent=Decimal("2.00"), attempts=0, user_monthly=Decimal("1.00"))
    with pytest.raises(BudgetExceededError, match="per-user cap"):
        await spend.check_budget(None, make_settings("10", "25"), OWNER_ID)


async def test_per_user_monthly_override_looser_than_global_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-user monthly cap ABOVE the global lets this owner keep spending
    past the global line — the override replaces, not min()s, the global."""
    _patch_ledger(monkeypatch, spent=Decimal("15.00"), attempts=0, user_monthly=Decimal("50.00"))
    await spend.check_budget(None, make_settings("10", "25"), OWNER_ID)  # no raise


async def test_per_user_daily_override_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ledger(monkeypatch, spent=Decimal("0"), attempts=3, user_daily=3)
    with pytest.raises(BudgetExceededError, match="per-user cap"):
        await spend.check_budget(None, make_settings("10", "25"), OWNER_ID)


async def test_null_columns_fall_back_to_global(monkeypatch: pytest.MonkeyPatch) -> None:
    """NULL per-user columns ⇒ the global env cap applies (both directions):
    under the global passes, at the global blocks with the ENV-VAR source."""
    _patch_ledger(monkeypatch, spent=Decimal("9.99"), attempts=24)  # both None
    await spend.check_budget(None, make_settings("10", "25"), OWNER_ID)  # under global

    _patch_ledger(monkeypatch, spent=Decimal("10.00"), attempts=0)
    with pytest.raises(BudgetExceededError, match="MONTHLY_LLM_BUDGET_USD"):
        await spend.check_budget(None, make_settings("10", "25"), OWNER_ID)


async def test_per_user_cap_cannot_bypass_failclosed_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The global switch is the master: a generous per-user cap does NOT
    re-enable paid calls when the global env budget is unset (fail-closed)."""
    calls = _patch_ledger(
        monkeypatch, spent=Decimal("0"), attempts=0, user_monthly=Decimal("999")
    )
    with pytest.raises(ConfigError):
        await spend.check_budget(None, make_settings(monthly=""), OWNER_ID)
    assert calls["caps"] == 0  # config parse refused before the caps read


async def test_two_users_different_caps_gated_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same global env; two owners with different per-user caps and different
    spend are each gated against their OWN effective cap."""
    settings = make_settings("10", "25")
    caps = {"low": (Decimal("1.00"), None), "high": (Decimal("100.00"), None)}
    spent = {"low": Decimal("2.00"), "high": Decimal("2.00")}

    async def fake_caps(session, owner_id):
        return caps[owner_id]

    async def fake_month(session, owner_id):
        return spent[owner_id]

    async def fake_day(session, owner_id):
        return 0

    monkeypatch.setattr(spend, "read_user_caps", fake_caps)
    monkeypatch.setattr(spend, "month_to_date_usd", fake_month)
    monkeypatch.setattr(spend, "attempts_today", fake_day)

    # $2 spent: over the "low" user's $1 cap, under the "high" user's $100 cap.
    with pytest.raises(BudgetExceededError):
        await spend.check_budget(None, settings, "low")
    await spend.check_budget(None, settings, "high")  # no raise


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


def _patch_alert_reads(
    monkeypatch: pytest.MonkeyPatch,
    *,
    spent: Decimal,
    attempts: int = 0,
    user_monthly: Decimal | None = None,
    user_daily: int | None = None,
) -> list[tuple[str, int]]:
    """Patch the alert path's three reads + capture. Returns the capture list."""
    captured: list[tuple[str, int]] = []

    async def fake_month(session, owner_id):
        return spent

    async def fake_attempts(session, owner_id):
        return attempts

    async def fake_caps(session, owner_id):
        return user_monthly, user_daily

    monkeypatch.setattr(spend, "month_to_date_usd", fake_month)
    monkeypatch.setattr(spend, "attempts_today", fake_attempts)
    monkeypatch.setattr(spend, "read_user_caps", fake_caps)
    monkeypatch.setattr(
        spend.observability, "capture_budget_alert", lambda msg, pct: captured.append((msg, pct))
    )
    return captured


async def test_alert_budget_progress_logs_and_captures(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # after this attempt's 0.20 the month is 8.10; before was 7.90 (crosses 80%).
    captured = _patch_alert_reads(monkeypatch, spent=Decimal("8.10"), attempts=1)

    import logging

    with caplog.at_level(logging.WARNING, logger="chefclaw.spend"):
        await spend.alert_budget_progress(None, make_settings(), OWNER_ID, Decimal("0.20"))

    (record,) = [r for r in caplog.records if r.name == "chefclaw.spend"]
    assert record.budget_pct == 80
    ((message, pct),) = captured
    assert pct == 80
    assert "80%" in message


async def test_alert_measures_against_per_user_monthly_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 80% crossing is measured against the per-user cap ($2), so it fires
    at $1.60 — the global $10 budget would not have crossed anything."""
    captured = _patch_alert_reads(
        monkeypatch, spent=Decimal("1.60"), attempts=1, user_monthly=Decimal("2.00")
    )
    await spend.alert_budget_progress(None, make_settings("10", "25"), OWNER_ID, Decimal("0.10"))
    ((message, pct),) = captured
    assert pct == 80
    assert "per-user cap" in message


async def test_alert_daily_cap_reached_fires_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reaching the per-user daily cap (5) alerts; the monthly $ is well under."""
    captured = _patch_alert_reads(
        monkeypatch, spent=Decimal("0.05"), attempts=5, user_daily=5
    )
    await spend.alert_budget_progress(None, make_settings("10", "25"), OWNER_ID, Decimal("0.01"))
    ((message, pct),) = captured
    assert pct == 100
    assert "daily extraction attempt cap reached" in message
    assert "per-user cap" in message


async def test_alert_daily_cap_not_yet_reached_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_alert_reads(
        monkeypatch, spent=Decimal("0.05"), attempts=4, user_daily=5
    )
    await spend.alert_budget_progress(None, make_settings("10", "25"), OWNER_ID, Decimal("0.01"))
    assert captured == []


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
