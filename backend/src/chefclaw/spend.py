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
from chefclaw.models import LlmSpend, User

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


# ─── Per-user caps (M3, ADR 2026-07-07-per-user-budget-caps) ──────────────────


async def read_user_caps(
    session: AsyncSession, owner_id: uuid.UUID
) -> tuple[Decimal | None, int | None]:
    """The owner's per-user cap columns, or (None, None) when unset/no row.

    NULL on a column means 'use the global default'. This is READ INSIDE THE
    GATE'S OWN SESSION (see :func:`check_budget`), between the fail-closed
    config parse and the ledger reads, so the caps share the paid-call read
    snapshot — the concurrency-1 double-spend gate is preserved
    (docs/adr/2026-07-06-jobs-without-broker.md)."""
    row = (
        await session.execute(
            select(User.monthly_budget_usd, User.max_attempts_per_day).where(User.id == owner_id)
        )
    ).first()
    if row is None:
        return None, None
    return row.monthly_budget_usd, row.max_attempts_per_day


# ─── The gate ────────────────────────────────────────────────────────────────

_PER_USER_CAP = "per-user cap for this account"  # message label for an override


async def check_budget(session: AsyncSession, settings: "Settings", owner_id: uuid.UUID) -> None:
    """The paid-call gate — CALL IMMEDIATELY BEFORE EVERY PAID CALL.

    Order matters and is load-bearing:
      1. Global config parse (ConfigError, fail-closed, NO reads) — a per-user
         cap can NEVER re-enable spend the operator hasn't globally enabled.
      2. Per-user cap read (this session) — a non-NULL column OVERRIDES the
         global default (higher or lower); NULL falls back to it.
      3. The cheap ledger reads, compared against the effective cap.
    Raises BudgetExceededError (monthly budget or daily attempt cap) or
    ConfigError. Performs no writes — the attempt is recorded by
    :func:`record_spend` after the call outcome is known.
    """
    global_monthly, global_daily = parse_budget(settings)

    user_monthly, user_daily = await read_user_caps(session, owner_id)
    monthly_budget = user_monthly if user_monthly is not None else global_monthly
    daily_attempts = user_daily if user_daily is not None else global_daily

    spent = await month_to_date_usd(session, owner_id)
    if spent >= monthly_budget:
        source = _PER_USER_CAP if user_monthly is not None else "MONTHLY_LLM_BUDGET_USD"
        raise BudgetExceededError(
            f"monthly LLM budget reached: ${spent} spent >= ${monthly_budget} "
            f"({source}) — no more paid calls this month."
        )

    attempts = await attempts_today(session, owner_id)
    if attempts >= daily_attempts:
        source = _PER_USER_CAP if user_daily is not None else "MAX_EXTRACTION_ATTEMPTS_PER_DAY"
        raise BudgetExceededError(
            f"daily extraction attempt cap reached: {attempts} attempts today >= "
            f"{daily_attempts} ({source}) — try again tomorrow."
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
    """After a ledger write: crossing-edge alerts (log + Sentry) for THIS owner
    — the monthly $ budget at 80%/100%, and the daily attempt cap when it is
    reached — each measured against the owner's EFFECTIVE cap (the per-user
    override when set, else the global env cap; M3). Best-effort by design:
    alerting must NEVER break the ledger write it follows, so every failure path
    degrades to a debug log."""
    try:
        global_monthly, global_daily = parse_budget(settings)
    except ConfigError:
        return  # fail-closed config ⇒ no paid calls happen; nothing to alert on
    try:
        user_monthly, user_daily = await read_user_caps(session, owner_id)
    except Exception:
        logger.debug("budget-alert per-user cap read failed", exc_info=True)
        user_monthly, user_daily = None, None
    monthly_budget = user_monthly if user_monthly is not None else global_monthly
    daily_cap = user_daily if user_daily is not None else global_daily
    monthly_src = "per-user cap" if user_monthly is not None else "MONTHLY_LLM_BUDGET_USD"

    # ── monthly $ budget: 80% / 100% crossings ──
    try:
        after = await month_to_date_usd(session, owner_id)
    except Exception:
        logger.debug("budget-alert ledger read failed", exc_info=True)
        after = None
    if after is not None:
        for pct in thresholds_crossed(after - attempt_cost, after, monthly_budget):
            message = (
                f"LLM spend crossed {pct}% of the monthly budget: "
                f"${after} of ${monthly_budget} ({monthly_src})"
            )
            logger.warning(
                message,
                extra={
                    "budget_pct": pct,
                    "spend_month_usd": float(after),
                    "budget_monthly_usd": float(monthly_budget),
                    "owner_id": str(owner_id),
                },
            )
            observability.capture_budget_alert(message, pct)

    # ── daily attempt cap: fire once on the attempt that REACHES it ──
    # record_spend writes exactly one row per call, so attempts_today rises by
    # one each time — the cap is crossed exactly when the count equals it.
    try:
        attempts = await attempts_today(session, owner_id)
    except Exception:
        logger.debug("daily-cap-alert ledger read failed", exc_info=True)
        attempts = None
    if attempts is not None and attempts == daily_cap:
        daily_src = "per-user cap" if user_daily is not None else "MAX_EXTRACTION_ATTEMPTS_PER_DAY"
        message = (
            f"daily extraction attempt cap reached: {attempts} of {daily_cap} "
            f"({daily_src}) — no more paid calls today"
        )
        logger.warning(
            message,
            extra={"daily_attempts": attempts, "daily_cap": daily_cap, "owner_id": str(owner_id)},
        )
        observability.capture_budget_alert(message, 100)


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


# ─── Admin cross-user rollup (GET /api/admin/spend — M3) ─────────────────────


@dataclass(frozen=True)
class UserSpend:
    """One user's month-to-date spend + effective caps for the admin rollup.
    ``budget_monthly_usd``/``daily_attempt_cap`` are the EFFECTIVE caps (the
    per-user override when set, else the global env default; None under
    fail-closed config); ``cap_is_personal`` marks a per-user monthly override."""

    id: uuid.UUID
    email: str
    paid_tier: bool
    month_to_date_usd: Decimal
    attempts_today: int
    budget_monthly_usd: Decimal | None
    daily_attempt_cap: int | None
    cap_is_personal: bool


@dataclass(frozen=True)
class AdminSpendSummary:
    """Whole-tenant spend rollup (admin only): every user's month-to-date spend
    and effective caps, plus tenant totals and the global env defaults."""

    total_month_to_date_usd: Decimal
    total_attempts_today: int
    global_budget_monthly_usd: Decimal | None
    global_daily_attempt_cap: int | None
    users: list[UserSpend]


async def admin_spend_summary(session: AsyncSession, settings: "Settings") -> AdminSpendSummary:
    """Aggregate month-to-date spend + today's attempts PER user across the
    whole tenant (owner-scoped ledger sums grouped by owner), joined to each
    user's effective caps. Friends-scale — a handful of users and two small
    GROUP BYs; no per-day history (that stays the per-owner /api/spend)."""
    try:
        global_monthly, global_daily = parse_budget(settings)
    except ConfigError:
        global_monthly, global_daily = None, None

    now = datetime.now(UTC)
    mtd_by_owner: dict[uuid.UUID, Decimal] = dict(
        (
            await session.execute(
                select(LlmSpend.owner_id, func.coalesce(func.sum(LlmSpend.cost_usd), 0))
                .where(LlmSpend.created_at >= month_start(now))
                .group_by(LlmSpend.owner_id)
            )
        ).all()
    )
    attempts_by_owner: dict[uuid.UUID, int] = dict(
        (
            await session.execute(
                select(LlmSpend.owner_id, func.count(LlmSpend.id))
                .where(LlmSpend.created_at >= day_start(now))
                .group_by(LlmSpend.owner_id)
            )
        ).all()
    )
    user_rows = (
        await session.execute(
            select(
                User.id,
                User.email,
                User.paid_tier,
                User.monthly_budget_usd,
                User.max_attempts_per_day,
            ).order_by(User.email)
        )
    ).all()

    users: list[UserSpend] = []
    total_mtd = Decimal(0)
    total_attempts = 0
    for u in user_rows:
        mtd = Decimal(mtd_by_owner.get(u.id, 0))
        attempts = int(attempts_by_owner.get(u.id, 0))
        total_mtd += mtd
        total_attempts += attempts
        users.append(
            UserSpend(
                id=u.id,
                email=u.email,
                paid_tier=u.paid_tier,
                month_to_date_usd=mtd,
                attempts_today=attempts,
                budget_monthly_usd=(
                    u.monthly_budget_usd if u.monthly_budget_usd is not None else global_monthly
                ),
                daily_attempt_cap=(
                    u.max_attempts_per_day if u.max_attempts_per_day is not None else global_daily
                ),
                cap_is_personal=u.monthly_budget_usd is not None,
            )
        )
    return AdminSpendSummary(
        total_month_to_date_usd=total_mtd,
        total_attempts_today=total_attempts,
        global_budget_monthly_usd=global_monthly,
        global_daily_attempt_cap=global_daily,
        users=users,
    )
