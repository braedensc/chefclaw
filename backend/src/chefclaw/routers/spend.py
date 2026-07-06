"""GET /api/spend — the ledger history readout (V2-A ADR).

Thin transport over :func:`chefclaw.spend.spend_summary`: the router only
regroups the flat (day, model) buckets into per-day objects for the UI.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from chefclaw.auth import require_owner
from chefclaw.routers.deps import get_spend_reader
from chefclaw.schemas import SpendDay, SpendModelSlice, SpendSummaryOut
from chefclaw.services.repo import SpendReader
from chefclaw.spend import SpendSummary

router = APIRouter(prefix="/api/spend", tags=["spend"])


def _to_response(summary: SpendSummary) -> SpendSummaryOut:
    days: dict[object, SpendDay] = {}
    for row in summary.rows:  # rows arrive newest-day-first, model-sorted
        day = days.get(row.day)
        if day is None:
            day = days[row.day] = SpendDay(date=row.day, cost_usd=0.0, attempts=0, models=[])
        day.cost_usd += float(row.cost_usd)
        day.attempts += row.attempts
        day.models.append(
            SpendModelSlice(
                model=row.model,
                cost_usd=float(row.cost_usd),
                attempts=row.attempts,
                tokens_in=row.tokens_in,
                tokens_out=row.tokens_out,
                tokens_thinking=row.tokens_thinking,
            )
        )
    return SpendSummaryOut(
        period_days=summary.period_days,
        total_usd=float(sum((row.cost_usd for row in summary.rows), start=0)),
        month_to_date_usd=float(summary.month_to_date_usd),
        attempts_today=summary.attempts_today,
        budget_monthly_usd=(
            float(summary.budget_monthly_usd) if summary.budget_monthly_usd is not None else None
        ),
        daily_attempt_cap=summary.daily_attempt_cap,
        days=list(days.values()),
    )


@router.get("", response_model=SpendSummaryOut)
async def get_spend(
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    reader: Annotated[SpendReader, Depends(get_spend_reader)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> SpendSummaryOut:
    """Per-day, per-model spend over the last ``days`` UTC days, plus
    month-to-date and the configured caps (null caps = fail-closed config)."""
    return _to_response(await reader.summary(owner_id, days=days))
