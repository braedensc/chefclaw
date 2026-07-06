"""GET /api/spend transport tests — CI tier, fake reader, no database.

The real per-day/per-model SQL is exercised by the golden DB tier
(test_spend_db.py, ``-m golden``); here we prove auth, the day-grouping
transform, param validation, and the fail-closed null-caps passthrough.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from chefclaw.routers.deps import get_spend_reader
from chefclaw.spend import DailyModelSpend, SpendSummary
from tests.conftest import TEST_TOKEN, bearer, make_app


def make_summary(**overrides) -> SpendSummary:
    fields = dict(
        period_days=30,
        month_to_date_usd=Decimal("1.25"),
        attempts_today=3,
        budget_monthly_usd=Decimal("10"),
        daily_attempt_cap=25,
        rows=[
            # Two models on the same (newest) day + one older single-model day.
            DailyModelSpend(
                day=date(2026, 7, 6), model="gemini-2.5-flash", cost_usd=Decimal("0.30"),
                attempts=2, tokens_in=1000, tokens_out=200, tokens_thinking=0,
            ),
            DailyModelSpend(
                day=date(2026, 7, 6), model="qwen3-vl-plus", cost_usd=Decimal("0.10"),
                attempts=1, tokens_in=500, tokens_out=100, tokens_thinking=0,
            ),
            DailyModelSpend(
                day=date(2026, 7, 4), model="gemini-2.5-flash", cost_usd=Decimal("0.85"),
                attempts=4, tokens_in=4000, tokens_out=800, tokens_thinking=50,
            ),
        ],
    )
    fields.update(overrides)
    return SpendSummary(**fields)


class FakeSpendReader:
    def __init__(self, summary: SpendSummary) -> None:
        self._summary = summary
        self.calls: list[tuple[uuid.UUID, int]] = []

    async def summary(self, owner_id: uuid.UUID, *, days: int) -> SpendSummary:
        self.calls.append((owner_id, days))
        return self._summary


@pytest.fixture
async def spend_client() -> AsyncIterator[tuple[AsyncClient, FakeSpendReader]]:
    reader = FakeSpendReader(make_summary())
    app = make_app()
    app.dependency_overrides[get_spend_reader] = lambda: reader
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client, reader


async def test_spend_401_without_token(spend_client) -> None:
    http_client, _ = spend_client
    response = await http_client.get("/api/spend")
    assert response.status_code == 401


async def test_spend_groups_days_and_passes_caps(spend_client) -> None:
    http_client, reader = spend_client
    response = await http_client.get("/api/spend", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    body = response.json()

    assert body["period_days"] == 30
    assert body["month_to_date_usd"] == 1.25
    assert body["attempts_today"] == 3
    assert body["budget_monthly_usd"] == 10.0
    assert body["daily_attempt_cap"] == 25
    assert body["total_usd"] == 1.25  # 0.30 + 0.10 + 0.85

    newest, older = body["days"]  # rows arrive newest first; grouping keeps it
    assert newest["date"] == "2026-07-06"
    assert newest["attempts"] == 3
    assert newest["cost_usd"] == pytest.approx(0.40)
    assert [m["model"] for m in newest["models"]] == ["gemini-2.5-flash", "qwen3-vl-plus"]
    assert older["date"] == "2026-07-04"
    assert older["models"][0]["tokens_thinking"] == 50

    (call,) = reader.calls
    assert call[1] == 30  # the documented default window


async def test_spend_days_param_is_validated_and_forwarded(spend_client) -> None:
    http_client, reader = spend_client
    assert (
        await http_client.get("/api/spend?days=7", headers=bearer(TEST_TOKEN))
    ).status_code == 200
    assert reader.calls[-1][1] == 7
    for bad in ("0", "366", "-1", "abc"):
        response = await http_client.get(f"/api/spend?days={bad}", headers=bearer(TEST_TOKEN))
        assert response.status_code == 422, f"days={bad} must be rejected"


async def test_spend_failclosed_caps_are_null(spend_client) -> None:
    """Fail-closed budget config surfaces as null caps — the UI says
    'extraction disabled', it never invents a number (§16.8 posture)."""
    http_client, reader = spend_client
    reader._summary = make_summary(budget_monthly_usd=None, daily_attempt_cap=None)
    body = (await http_client.get("/api/spend", headers=bearer(TEST_TOKEN))).json()
    assert body["budget_monthly_usd"] is None
    assert body["daily_attempt_cap"] is None
