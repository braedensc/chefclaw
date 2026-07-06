"""FastAPI app factory: API routes first, then optional SPA static mount.

The lifespan owns the in-process extraction worker: ONE asyncio task, jobs
strictly serial (no-broker hard constraint). httpx's ASGITransport never runs
lifespan, so the unit-test tier gets an app with no worker and no DB touch.
"""

import asyncio
import contextlib
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chefclaw import db, observability, spend
from chefclaw.auth import require_owner
from chefclaw.config import Settings, get_settings
from chefclaw.errors import ConfigError
from chefclaw.extractors import extractor_model_id
from chefclaw.routers.extraction import router as extraction_router
from chefclaw.routers.jobs import router as jobs_router
from chefclaw.routers.library import router as library_router
from chefclaw.routers.spend import router as spend_router
from chefclaw.services.jobs import Worker, default_source_adapters
from chefclaw.services.repo import PostgresJobStore

# Rednote cookies live 2–4 weeks (plan §10): warn at 14 days (aging), alarm
# at 21 (stale) — proactive, BEFORE the expiry window closes.
COOKIE_AGING_DAYS = 14
COOKIE_STALE_DAYS = 21
# Backups are launchd-scheduled daily (ops/com.chefclaw.backup.plist.example);
# 26h = one cycle plus slack, so a single missed run already shows 'stale'.
BACKUP_STALE_HOURS = 26
# A finished_at in the FUTURE is corrupted state or serious clock skew — it
# must warn, not report 'fresh' until the bogus date arrives. Small negative
# ages (container-vs-host drift after a laptop sleep) stay tolerated.
BACKUP_FUTURE_SLACK_HOURS = 0.5
_SIDECAR_PROBE_TIMEOUT_SECONDS = 1.0


class HealthResponse(BaseModel):
    """Phase-4 health shape (plan §7 screen 4): sidecar + cookie + backup
    staleness + spend readout, plus which extractor/model is live. New fields
    keep schema-level defaults so the generated TS client treats them as
    optional — the endpoint always sets them explicitly."""

    status: Literal["ok", "degraded"]
    db: Literal["ok", "unreachable"]
    sidecar: Literal["ok", "unreachable", "not_configured"] = "not_configured"
    cookie_freshness: Literal["fresh", "aging", "stale", "not_configured"] = "not_configured"
    # The raw XHS_COOKIE_SET_DATE string (None when no cookie is configured).
    # Surfaced verbatim so the Settings screen can show WHEN the cookie was
    # set next to the freshness bucket — an unparseable value still shows
    # (bucket says 'stale'; seeing the typo is the fastest fix).
    cookie_set_date: str | None = None
    # 'fresh' = last run ok and < BACKUP_STALE_HOURS old; 'stale' = old,
    # failed, or unreadable state; 'not_configured' = no state file yet.
    backup: Literal["fresh", "stale", "not_configured"] = "not_configured"
    backup_finished_at: str | None = None
    extractor: str = "fake"
    model: str = "fake-extractor"
    spend_month_usd: float | None = None
    # V2-A additions. Caps are null when the budget config is fail-closed
    # (unset/unparseable) — the UI says "extraction disabled", never invents
    # a number; attempts_today is null when the ledger could not be read.
    budget_monthly_usd: float | None = None
    daily_attempt_cap: int | None = None
    attempts_today: int | None = None
    # Worker aliveness is task-not-done, NOT a heartbeat timestamp — a
    # timestamp false-alarms during any long legitimate download/extract
    # stage; the real failure mode is the asyncio task dying while the api
    # keeps answering. 'not_running' = no lifespan (unit tests).
    worker: Literal["alive", "dead", "not_running"] = "not_running"
    sentry_enabled: bool = False


def _backup_status(
    settings: Settings, *, now: datetime | None = None
) -> tuple[Literal["fresh", "stale", "not_configured"], str | None]:
    """Backup freshness from the state file scripts/backup.sh writes
    (bind-mounted read-only at /data/ops). NEVER raises: a missing file is
    'not_configured'; anything unreadable/failed/old fails toward 'stale' —
    the warning must never hide (same posture as cookie freshness)."""
    state_path = Path(settings.backup_state_file)
    try:
        raw = state_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "not_configured", None
    except OSError:
        # The file EXISTS but can't be read (permissions, a directory in its
        # place, …) — that is a broken backup signal, not "never configured":
        # saying 'not_configured' would tell the operator to set up backups
        # they already have. Warn instead.
        return "stale", None
    try:
        state = json.loads(raw)
        finished_at_raw = state["finished_at"]
        finished_at = datetime.fromisoformat(finished_at_raw)
        ok = state["ok"] is True
    except (ValueError, KeyError, TypeError):
        return "stale", None  # unreadable state ⇒ warn, never 500
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=UTC)
    if not ok:
        return "stale", finished_at_raw
    age_hours = ((now or datetime.now(UTC)) - finished_at).total_seconds() / 3600
    if age_hours < -BACKUP_FUTURE_SLACK_HOURS:
        # A future finished_at would otherwise read 'fresh' until the bogus
        # date arrives — potentially years of a dead backup looking healthy.
        return "stale", finished_at_raw
    if age_hours >= BACKUP_STALE_HOURS:
        return "stale", finished_at_raw
    return "fresh", finished_at_raw


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


async def _attempts_today(owner_id: uuid.UUID) -> int | None:
    """Today's ledger attempt count (same never-raises contract as above)."""
    try:
        async with db.get_sessionmaker()() as session:
            return await spend.attempts_today(session, owner_id)
    except Exception:
        return None


def _budget_caps(settings: Settings) -> tuple[float | None, int | None]:
    """The configured caps, or (None, None) under fail-closed config — the
    same parse the paid-call gate uses, so health and the gate can't drift."""
    try:
        monthly, daily = spend.parse_budget(settings)
    except ConfigError:
        return None, None
    return float(monthly), daily


def _worker_status(app: FastAPI) -> Literal["alive", "dead", "not_running"]:
    """'dead' is the silent killer this exists for: the worker task crashed
    but the api still answers — no job would ever run again."""
    task: asyncio.Task | None = getattr(app.state, "worker_task", None)
    if task is None:
        return "not_running"
    return "dead" if task.done() else "alive"


api_router = APIRouter(prefix="/api")


@api_router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Health check. NOT publicly exempt from auth — it exposes spend/cookie
    state (plan §16 amendment 3)."""
    db_ok = await db.ping()
    backup, backup_finished_at = _backup_status(settings)
    budget_monthly_usd, daily_attempt_cap = _budget_caps(settings)
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db="ok" if db_ok else "unreachable",
        sidecar=await _sidecar_status(settings),
        cookie_freshness=_cookie_freshness(settings.xhs_cookie_set_date),
        cookie_set_date=settings.xhs_cookie_set_date.strip() or None,
        backup=backup,
        backup_finished_at=backup_finished_at,
        extractor=settings.chefclaw_extractor,
        model=extractor_model_id(settings),
        spend_month_usd=await _spend_month_to_date(owner_id) if db_ok else None,
        budget_monthly_usd=budget_monthly_usd,
        daily_attempt_cap=daily_attempt_cap,
        attempts_today=await _attempts_today(owner_id) if db_ok else None,
        worker=_worker_status(request.app),
        sentry_enabled=observability.sentry_enabled(),
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
    # Health reads aliveness off this: a done() task = the worker died while
    # the api keeps answering (the failure mode worth surfacing).
    app.state.worker_task = task
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
    # Structured request log for /api/* (method/path/status/latency/owner —
    # never query strings, headers, or bodies). Logging + Sentry themselves
    # are configured at the PROCESS entrypoint (main.py), not here — the app
    # factory must stay side-effect-free for the unit-test tier.
    app.add_middleware(observability.RequestLogMiddleware)
    app.include_router(api_router)
    app.include_router(extraction_router)
    app.include_router(jobs_router)
    app.include_router(library_router)
    app.include_router(spend_router)

    # Serve the built SPA same-origin in prod. CHEFCLAW_STATIC_DIR unset =>
    # skip (dev mode uses the Vite proxy instead). Mounted AFTER api routes
    # so /api/* always wins.
    static_dir = get_settings().chefclaw_static_dir
    if static_dir:
        static_path = Path(static_dir)
        if static_path.is_dir():
            app.mount("/", StaticFiles(directory=static_path, html=True), name="spa")

    return app
