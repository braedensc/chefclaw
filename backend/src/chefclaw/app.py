"""FastAPI app factory: API routes first, then optional SPA static mount."""

import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chefclaw import db
from chefclaw.auth import require_owner
from chefclaw.config import get_settings


class HealthResponse(BaseModel):
    """Extensible Phase-1 health shape.

    sidecar / cookie_freshness / backup / spend_month_usd are placeholders
    whose real values land in later phases (plan §7 screen 4).
    """

    status: Literal["ok", "degraded"]
    db: Literal["ok", "unreachable"]
    sidecar: Literal["not_configured"] = "not_configured"
    cookie_freshness: Literal["not_configured"] = "not_configured"
    backup: Literal["not_configured"] = "not_configured"
    spend_month_usd: float | None = None


api_router = APIRouter(prefix="/api")


@api_router.get("/health", response_model=HealthResponse)
async def health(
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
) -> HealthResponse:
    """Health check. NOT publicly exempt from auth — it exposes spend/cookie
    state (plan §16 amendment 3)."""
    db_ok = await db.ping()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db="ok" if db_ok else "unreachable",
        spend_month_usd=None,
    )


def create_app() -> FastAPI:
    """Build the application: API routes, then the SPA mount (prod mode)."""
    app = FastAPI(title="chefclaw", version="0.1.0")
    app.include_router(api_router)

    # Serve the built SPA same-origin in prod. CHEFCLAW_STATIC_DIR unset =>
    # skip (dev mode uses the Vite proxy instead). Mounted AFTER api routes
    # so /api/* always wins.
    static_dir = get_settings().chefclaw_static_dir
    if static_dir:
        static_path = Path(static_dir)
        if static_path.is_dir():
            app.mount("/", StaticFiles(directory=static_path, html=True), name="spa")

    return app
