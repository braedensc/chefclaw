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

import uuid
from datetime import UTC, datetime
from decimal import ROUND_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chefclaw.errors import BudgetExceededError, ConfigError
from chefclaw.extractors import ExtractionUsage
from chefclaw.models import LlmSpend

if TYPE_CHECKING:
    from chefclaw.config import Settings

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
    # The fake extractor is genuinely free. Its ledger rows still count toward
    # the daily attempt cap (attempts_today counts rows, not dollars).
    "fake-extractor": (Decimal("0"), Decimal("0")),
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
