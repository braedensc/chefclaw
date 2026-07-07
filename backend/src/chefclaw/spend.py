"""Cost guardrails — budget parsing, the paid-call gate, and the spend ledger
(plan §10, §16.8).

FAIL-CLOSED is the whole design: `MONTHLY_LLM_BUDGET_USD` /
`MAX_EXTRACTION_ATTEMPTS_PER_DAY` unset, unparseable, or non-positive means NO
paid calls, surfaced as a typed :class:`~chefclaw.errors.ConfigError`.
:func:`check_budget` runs IMMEDIATELY BEFORE EVERY PAID CALL — not just at
enqueue; retries are the leak path. The check is deliberately cheap (two
reads, no writes); the attempt itself is recorded afterwards via
:func:`record_spend`, one ledger row PER MODEL ATTEMPT INCLUDING FAILURES
(a failed generate that consumed tokens still writes; a call that never
reached the API writes nothing). ``attempts_today`` counts ledger rows, so
the daily cap bounds runaway retries even when a failed attempt's token
counts are unknown and recorded as zero.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chefclaw import observability
from chefclaw.errors import BudgetExceededError, ConfigError
from chefclaw.extractors import ExtractionUsage
from chefclaw.models import LlmSpend

if TYPE_CHECKING:
    from chefclaw.config import Settings

logger = logging.getLogger(__name__)

# ─── Pricing table ───────────────────────────────────────────────────────────
# !!! RE-VERIFY THESE NUMBERS AGAINST LIVE GEMINI PRICING BEFORE TRUSTING !!!
# (https://ai.google.dev/gemini-api/docs/pricing — prices move faster than any
# code review; last eyeballed 2026-07.) Values are USD per 1M tokens, keyed by
# model-id PREFIX, and DELIBERATELY padded ABOVE the published list price —
# kit rule: the kill-switch trips EARLY, never late. Over-counting wastes a
# few cents of headroom; under-counting is a leak. Thinking tokens are billed
# at the OUTPUT rate (also the conservative choice).
GEMINI_PRICING: dict[str, tuple[Decimal, Decimal]] = {
    # prefix: (usd_per_1M_tokens_in, usd_per_1M_tokens_out)
    "gemini-2.5-pro": (Decimal("2.50"), Decimal("15.00")),
    "gemini-2.5-flash-lite": (Decimal("0.40"), Decimal("3.20")),
    "gemini-2.5-flash": (Decimal("0.60"), Decimal("5.00")),
    # The fake extractor / fake image generator are genuinely free. Their
    # ledger rows still count toward the daily attempt cap (attempts_today
    # counts rows, not dollars).
    "fake-extractor": (Decimal("0"), Decimal("0")),
    "fake-image": (Decimal("0"), Decimal("0")),
    # Image models bill a FLAT per-image cost, NOT per token — the illustration
    # stage passes that flat cost straight to record_spend and never routes
    # through estimate_cost. This entry only guards _rates_for from ever being
    # asked for a zero-token image row and inventing a per-token rate; the
    # tokens are 0 so the dollar effect is nil regardless.
    "gemini-3.1-flash-image": (Decimal("0"), Decimal("0")),
    "gemini-2.5-flash-image": (Decimal("0"), Decimal("0")),
}

_COST_QUANTUM = Decimal("0.000001")  # matches llm_spend.cost_usd numeric(10,6)
_TOKENS_PER_UNIT = Decimal("1000000")


def _rates_for(model_id: str) -> tuple[Decimal, Decimal]:
    """Longest matching prefix wins; an UNKNOWN model id gets the most
    expensive known rates (conservative — never silently cheap)."""
    matches = [prefix for prefix in GEMINI_PRICING if model_id.startswith(prefix)]
    if matches:
        return GEMINI_PRICING[max(matches, key=len)]
    return max(GEMINI_PRICING.values(), key=lambda rates: rates[0] + rates[1])


def estimate_cost(usage: ExtractionUsage) -> Decimal:
    """Conservative USD cost of one model attempt (rounded UP to 6 places)."""
    rate_in, rate_out = _rates_for(usage.model_id)
    # Thinking tokens billed at the output rate — conservative (see above).
    billed_out = Decimal(usage.tokens_out) + Decimal(usage.tokens_thinking)
    raw = (rate_in * Decimal(usage.tokens_in) + rate_out * billed_out) / _TOKENS_PER_UNIT
    return raw.quantize(_COST_QUANTUM, rounding=ROUND_UP)


# ─── Budget config (fail-closed, §16.8) ──────────────────────────────────────


def parse_budget(settings: "Settings") -> tuple[Decimal, int]:
    """Parse the two budget env vars. Unset / unparseable / non-positive ⇒
    :class:`ConfigError` naming the env var — NO paid calls (fail-closed)."""
    raw_monthly = settings.monthly_llm_budget_usd.strip()
    if not raw_monthly:
        raise ConfigError(
            "MONTHLY_LLM_BUDGET_USD is unset — refusing all paid calls (fail-closed). "
            "Set it in the server environment (e.g. MONTHLY_LLM_BUDGET_USD=10)."
        )
    try:
        monthly = Decimal(raw_monthly)
    except InvalidOperation:
        raise ConfigError(
            f"MONTHLY_LLM_BUDGET_USD={raw_monthly!r} is not a number — refusing all "
            "paid calls (fail-closed). Set a positive dollar amount, e.g. 10."
        ) from None
    if not monthly.is_finite() or monthly <= 0:
        raise ConfigError(
            f"MONTHLY_LLM_BUDGET_USD={raw_monthly!r} must be a positive dollar amount — "
            "refusing all paid calls (fail-closed)."
        )

    raw_daily = settings.max_extraction_attempts_per_day.strip()
    if not raw_daily:
        raise ConfigError(
            "MAX_EXTRACTION_ATTEMPTS_PER_DAY is unset — refusing all paid calls "
            "(fail-closed). Set it in the server environment "
            "(e.g. MAX_EXTRACTION_ATTEMPTS_PER_DAY=25)."
        )
    try:
        daily = int(raw_daily)
    except ValueError:
        raise ConfigError(
            f"MAX_EXTRACTION_ATTEMPTS_PER_DAY={raw_daily!r} is not an integer — "
            "refusing all paid calls (fail-closed). Set a positive count, e.g. 25."
        ) from None
    if daily <= 0:
        raise ConfigError(
            f"MAX_EXTRACTION_ATTEMPTS_PER_DAY={raw_daily!r} must be a positive integer — "
            "refusing all paid calls (fail-closed)."
        )
    return monthly, daily


# ─── Ledger reads (UTC windows) ──────────────────────────────────────────────


def month_start(now: datetime) -> datetime:
    """First instant of the current UTC month."""
    utc_now = now.astimezone(UTC)
    return utc_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def day_start(now: datetime) -> datetime:
    """First instant of the current UTC day."""
    utc_now = now.astimezone(UTC)
    return utc_now.replace(hour=0, minute=0, second=0, microsecond=0)


async def month_to_date_usd(session: AsyncSession, owner_id: uuid.UUID) -> Decimal:
    """Sum of llm_spend.cost_usd for the current UTC month."""
    stmt = select(func.coalesce(func.sum(LlmSpend.cost_usd), 0)).where(
        LlmSpend.owner_id == owner_id,
        LlmSpend.created_at >= month_start(datetime.now(UTC)),
    )
    return Decimal(await session.scalar(stmt))


async def attempts_today(session: AsyncSession, owner_id: uuid.UUID) -> int:
    """Ledger rows (model ATTEMPTS, including failures) in the current UTC day."""
    stmt = select(func.count(LlmSpend.id)).where(
        LlmSpend.owner_id == owner_id,
        LlmSpend.created_at >= day_start(datetime.now(UTC)),
    )
    return int(await session.scalar(stmt))


# ─── The gate ────────────────────────────────────────────────────────────────


async def check_budget(session: AsyncSession, settings: "Settings", owner_id: uuid.UUID) -> None:
    """The paid-call gate — CALL IMMEDIATELY BEFORE EVERY PAID CALL.

    Order matters: config parse first (ConfigError, fail-closed, no reads),
    then the cheap ledger reads. Raises BudgetExceededError (monthly budget
    or daily attempt cap) or ConfigError. Performs no writes — the attempt is
    recorded by :func:`record_spend` after the call outcome is known.
    """
    monthly_budget, daily_attempts = parse_budget(settings)

    spent = await month_to_date_usd(session, owner_id)
    if spent >= monthly_budget:
        raise BudgetExceededError(
            f"monthly LLM budget reached: ${spent} spent >= ${monthly_budget} "
            "(MONTHLY_LLM_BUDGET_USD) — no more paid calls this month."
        )

    attempts = await attempts_today(session, owner_id)
    if attempts >= daily_attempts:
        raise BudgetExceededError(
            f"daily extraction attempt cap reached: {attempts} attempts today >= "
            f"{daily_attempts} (MAX_EXTRACTION_ATTEMPTS_PER_DAY) — try again tomorrow."
        )


async def record_spend(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    owner_id: uuid.UUID,
    usage: ExtractionUsage,
    cost_usd: Decimal,
) -> LlmSpend:
    """Write ONE ledger row for one model attempt (success OR failure) and
    commit it immediately — the ledger must survive whatever the job
    transaction does next."""
    row = LlmSpend(
        job_id=job_id,
        owner_id=owner_id,
        model=usage.model_id,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        tokens_thinking=usage.tokens_thinking,
        cost_usd=cost_usd,
    )
    session.add(row)
    await session.commit()
    return row


# ─── Budget alerting (V2-A ADR — crossing-edge, best-effort) ─────────────────

BUDGET_ALERT_THRESHOLDS: tuple[Decimal, ...] = (Decimal("0.80"), Decimal("1.00"))


def thresholds_crossed(before: Decimal, after: Decimal, budget: Decimal) -> list[int]:
    """Which alert thresholds (as percents: 80, 100) THIS attempt crossed.

    Crossing-edge (``before < line <= after``), so each threshold alerts on
    exactly the attempt that crosses it — never once per attempt for the rest
    of the month. One big attempt can legitimately cross both at once.
    """
    return [
        int(fraction * 100)
        for fraction in BUDGET_ALERT_THRESHOLDS
        if before < budget * fraction <= after
    ]


async def alert_budget_progress(
    session: AsyncSession,
    settings: "Settings",
    owner_id: uuid.UUID,
    attempt_cost: Decimal,
) -> None:
    """After a ledger write: warn (log + Sentry) when the month's spend
    crosses 80% / 100% of MONTHLY_LLM_BUDGET_USD. Best-effort by design —
    alerting must NEVER break the ledger write it follows, so every failure
    path here degrades to a debug log."""
    try:
        monthly_budget, _ = parse_budget(settings)
    except ConfigError:
        return  # fail-closed config ⇒ no paid calls happen; nothing to alert on
    try:
        after = await month_to_date_usd(session, owner_id)
    except Exception:
        logger.debug("budget-alert ledger read failed", exc_info=True)
        return
    for pct in thresholds_crossed(after - attempt_cost, after, monthly_budget):
        message = (
            f"LLM spend crossed {pct}% of the monthly budget: "
            f"${after} of ${monthly_budget} (MONTHLY_LLM_BUDGET_USD)"
        )
        logger.warning(
            message,
            extra={
                "budget_pct": pct,
                "spend_month_usd": float(after),
                "budget_monthly_usd": float(monthly_budget),
            },
        )
        observability.capture_budget_alert(message, pct)


# ─── Spend history (GET /api/spend — V2-A ADR) ───────────────────────────────


@dataclass(frozen=True)
class DailyModelSpend:
    """One (UTC day, model) aggregation bucket from the ledger."""

    day: date
    model: str
    cost_usd: Decimal
    attempts: int
    tokens_in: int
    tokens_out: int
    tokens_thinking: int


@dataclass(frozen=True)
class SpendSummary:
    """Everything the spend endpoint reports — assembled here so the router
    stays a thin transport. ``budget_monthly_usd``/``daily_attempt_cap`` are
    None when the budget config is fail-closed (unset/unparseable)."""

    period_days: int
    month_to_date_usd: Decimal
    attempts_today: int
    budget_monthly_usd: Decimal | None
    daily_attempt_cap: int | None
    rows: list[DailyModelSpend]


async def spend_by_day_and_model(
    session: AsyncSession, owner_id: uuid.UUID, *, days: int
) -> list[DailyModelSpend]:
    """Per-UTC-day, per-model ledger aggregation over the last ``days`` days
    (today included), newest day first."""
    since = day_start(datetime.now(UTC)) - timedelta(days=days - 1)
    # Explicit UTC bucketing: date_trunc on a timestamptz otherwise follows
    # the connection's TimeZone setting.
    day_col = func.date_trunc("day", func.timezone("UTC", LlmSpend.created_at))
    stmt = (
        select(
            day_col.label("day"),
            LlmSpend.model,
            func.sum(LlmSpend.cost_usd).label("cost_usd"),
            func.count(LlmSpend.id).label("attempts"),
            func.coalesce(func.sum(LlmSpend.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(LlmSpend.tokens_out), 0).label("tokens_out"),
            func.coalesce(func.sum(LlmSpend.tokens_thinking), 0).label("tokens_thinking"),
        )
        .where(LlmSpend.owner_id == owner_id, LlmSpend.created_at >= since)
        .group_by(day_col, LlmSpend.model)
        .order_by(day_col.desc(), LlmSpend.model)
    )
    result = await session.execute(stmt)
    return [
        DailyModelSpend(
            day=row.day.date() if isinstance(row.day, datetime) else row.day,
            model=row.model,
            cost_usd=Decimal(row.cost_usd),
            attempts=int(row.attempts),
            tokens_in=int(row.tokens_in),
            tokens_out=int(row.tokens_out),
            tokens_thinking=int(row.tokens_thinking),
        )
        for row in result
    ]


async def spend_summary(
    session: AsyncSession, settings: "Settings", owner_id: uuid.UUID, *, days: int
) -> SpendSummary:
    """The full spend readout. Budget caps come from the same fail-closed
    parse the paid-call gate uses — None here means 'extraction is refusing
    paid calls', and the UI says so instead of inventing a number."""
    try:
        budget, daily_cap = parse_budget(settings)
    except ConfigError:
        budget, daily_cap = None, None
    return SpendSummary(
        period_days=days,
        month_to_date_usd=await month_to_date_usd(session, owner_id),
        attempts_today=await attempts_today(session, owner_id),
        budget_monthly_usd=budget,
        daily_attempt_cap=daily_cap,
        rows=await spend_by_day_and_model(session, owner_id, days=days),
    )
