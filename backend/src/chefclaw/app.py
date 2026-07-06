"""FastAPI app factory: API routes first, then optional SPA static mount.

The lifespan owns the in-process extraction worker: ONE asyncio task, jobs
strictly serial (no-broker hard constraint). httpx's ASGITransport never runs
lifespan, so the unit-test tier gets an app with no worker and no DB touch.
"""

import asyncio
import contextlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chefclaw import db, spend
from chefclaw.auth import require_owner
from chefclaw.config import Settings, get_settings
from chefclaw.routers.extraction import router as extraction_router
from chefclaw.routers.jobs import router as jobs_router
from chefclaw.routers.library import router as library_router
from chefclaw.services.jobs import Worker, default_source_adapters
from chefclaw.services.repo import PostgresJobStore

# Rednote cookies live 2–4 weeks (plan §10): warn at 14 days (aging), alarm
# at 21 (stale) — proactive, BEFORE the expiry window closes.
COOKIE_AGING_DAYS = 14
COOKIE_STALE_DAYS = 21
_SIDECAR_PROBE_TIMEOUT_SECONDS = 1.0


class HealthResponse(BaseModel):
    """Phase-2 health shape (plan §7 screen 4). ``backup`` stays a
    placeholder until Phase 4's backup script lands."""

    status: Literal["ok", "degraded"]
    db: Literal["ok", "unreachable"]
    sidecar: Literal["ok", "unreachable", "not_configured"] = "not_configured"
    cookie_freshness: Literal["fresh", "aging", "stale", "not_configured"] = "not_configured"
    backup: Literal["not_configured"] = "not_configured"
    spend_month_usd: float | None = None


async def _sidecar_status(settings: Settings) -> Literal["ok", "unreachable", "not_configured"]:
    """Best-effort reachability probe (any HTTP answer counts as up)."""
    base = settings.xhs_sidecar_url.rstrip("/")
    if not base:
        return "not_configured"
    try:
        async with httpx.AsyncClient(timeout=_SIDECAR_PROBE_TIMEOUT_SECONDS) as client:
            await client.get(f"{base}/docs")
        return "ok"
    except Exception:
        # Broader than httpx.HTTPError on purpose: httpx.InvalidURL is NOT an
        # HTTPError (a stray \r in XHS_SIDECAR_URL raises it), and health must
        # NEVER 500 — a bad probe is "unreachable", not an exception.
        return "unreachable"


def _cookie_freshness(
    set_date_raw: str, *, today: date | None = None
) -> Literal["fresh", "aging", "stale", "not_configured"]:
    """Freshness from XHS_COOKIE_SET_DATE (human-written at every refresh —
    cookie age is not derivable from the cookie string itself)."""
    raw = set_date_raw.strip()
    if not raw:
        return "not_configured"
    try:
        set_date = date.fromisoformat(raw)
    except ValueError:
        return "stale"  # unparseable ⇒ fail toward the warning, never hide it
    age_days = ((today or datetime.now(UTC).date()) - set_date).days
    if age_days >= COOKIE_STALE_DAYS:
        return "stale"
    if age_days >= COOKIE_AGING_DAYS:
        return "aging"
    return "fresh"


async def _spend_month_to_date(owner_id: uuid.UUID) -> float | None:
    """Month-to-date ledger sum for the health readout. Never raises —
    ``null`` means 'could not read' (db down, etc.), not zero."""
    try:
        async with db.get_sessionmaker()() as session:
            value = await spend.month_to_date_usd(session, owner_id)
        return float(value)
    except Exception:
        return None


api_router = APIRouter(prefix="/api")


@api_router.get("/health", response_model=HealthResponse)
async def health(
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Health check. NOT publicly exempt from auth — it exposes spend/cookie
    state (plan §16 amendment 3)."""
    db_ok = await db.ping()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db="ok" if db_ok else "unreachable",
        sidecar=await _sidecar_status(settings),
        cookie_freshness=_cookie_freshness(settings.xhs_cookie_set_date),
        spend_month_usd=await _spend_month_to_date(owner_id) if db_ok else None,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Start/stop the strictly-serial extraction worker with the app."""
    settings = get_settings()
    worker = Worker(
        store=PostgresJobStore(db.get_sessionmaker(), settings),
        adapters=default_source_adapters(settings),
        settings=settings,
    )
    task = asyncio.create_task(worker.run_forever(), name="chefclaw-extraction-worker")
    try:
        yield
    finally:
        # Cancel mid-job leaves the job in its running stage on purpose —
        # the next boot's reconcile flips it to failed/interrupted (§4).
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    """Build the application: API routes, then the SPA mount (prod mode)."""
    app = FastAPI(title="chefclaw", version="0.1.0", lifespan=_lifespan)
    app.include_router(api_router)
    app.include_router(extraction_router)
    app.include_router(jobs_router)
    app.include_router(library_router)

    # Serve the built SPA same-origin in prod. CHEFCLAW_STATIC_DIR unset =>
    # skip (dev mode uses the Vite proxy instead). Mounted AFTER api routes
    # so /api/* always wins.
    static_dir = get_settings().chefclaw_static_dir
    if static_dir:
        static_path = Path(static_dir)
        if static_path.is_dir():
            app.mount("/", StaticFiles(directory=static_path, html=True), name="spa")

    return app
