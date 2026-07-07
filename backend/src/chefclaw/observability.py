"""Observability: structured JSON logging + DSN-gated Sentry (ADR
2026-07-06-observability-and-cost).

Both layers are opt-in by env presence and inert by default:

- Logging is configured ONCE at the process entrypoint (``main.py``), never in
  ``create_app()`` — the unit-test tier keeps pytest's own log capture intact.
- Sentry initialises ONLY when ``SENTRY_DSN`` is set (kit pattern,
  docs/STACK-RATIONALE.md): no DSN ⇒ ``sentry_sdk`` is never touched, so dev,
  CI, and tests send zero events by construction. Every ``capture_*`` helper
  below is safe to call uninitialised (the SDK no-ops).

Hard Rule 2 applies to every log line and every event: secret VALUES never
appear — the Sentry scrubber below adds our secret names to the SDK's default
denylist as a second net, not as permission to get close to the line.
"""

import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sentry_sdk
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

if TYPE_CHECKING:
    from chefclaw.config import Settings

logger = logging.getLogger(__name__)

_request_logger = logging.getLogger("chefclaw.request")

# Our secret env/field names, scrubbed from Sentry events on top of the SDK's
# defaults (which already cover generic names like api_key/token/authorization).
_SENTRY_DENYLIST = DEFAULT_DENYLIST + [
    "chefclaw_api_token",
    "gemini_api_key",
    "dashscope_api_key",
    "google_oauth_client_secret",
    "xhs_cookie",
    "bilibili_cookie",
    "db_password",
    "cookie",
    "set-cookie",
]

# Module truth for "is error tracking on" — sentry_sdk.is_initialized() reports
# True even for a disabled (DSN-less) client, so health reads THIS instead.
_sentry_enabled = False


# ─── Structured logging ──────────────────────────────────────────────────────

# Attributes every LogRecord carries; anything else on the record came in via
# ``extra=`` and is emitted as a structured JSON field.
_STANDARD_RECORD_ATTRS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """One JSON object per line on stdout — journald / ``docker compose logs``
    friendly. ``extra=`` fields ride along verbatim; non-JSON types fall back
    to ``str`` (UUIDs, Decimals, datetimes)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(settings: "Settings") -> None:
    """Root logging to stdout — JSON by default, ``CHEFCLAW_LOG_FORMAT=text``
    for a human-readable dev console. Called from the process entrypoint only
    (main.py), NEVER from create_app(): reconfiguring the root logger inside
    the app factory would wipe pytest's log capture in the unit tier."""
    handler = logging.StreamHandler()  # stderr; docker/journald capture both
    if settings.chefclaw_log_format == "text":
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    else:
        # Unknown values fall toward JSON — logging config must never crash
        # the app, and JSON is the value every deployed mode wants.
        handler.setFormatter(JsonFormatter())
    level = getattr(logging, settings.chefclaw_log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # The request middleware below replaces uvicorn's access line (which has
    # no latency, no owner scope, and no JSON) — silence the duplicate.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class RequestLogMiddleware:
    """Pure-ASGI request log for ``/api/*``: method, path, status, duration,
    and the resolved owner id (set by ``auth.require_owner`` via request
    state). Never the query string, never a header, never a body — paths in
    this API carry no secrets; everything else might.

    ``/api/health`` logs at DEBUG: the Settings screen polls it every 15 s and
    an INFO line per poll is noise pretending to be signal.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api"):
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope["path"]
            # No response start ⇒ the app raised before responding; the outer
            # ServerErrorMiddleware turns that into a 500.
            status = status_holder.get("status", 500)
            owner_id = scope.get("state", {}).get("owner_id")
            level = logging.DEBUG if path == "/api/health" else logging.INFO
            _request_logger.log(
                level,
                "%s %s -> %d",
                scope["method"],
                path,
                status,
                extra={
                    "http_method": scope["method"],
                    "http_path": path,
                    "http_status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    "owner_id": str(owner_id) if owner_id else None,
                },
            )


# ─── Sentry (DSN-gated) ──────────────────────────────────────────────────────


def init_sentry(settings: "Settings") -> bool:
    """Initialise Sentry IFF a DSN is configured; returns whether it is on.

    No DSN ⇒ ``sentry_sdk.init`` is never called — not "initialised but
    disabled", never touched. Tracing and replay stay off (error tracking
    only, free-tier friendly); the FastAPI/Starlette integrations auto-enable.
    """
    global _sentry_enabled
    if not settings.sentry_dsn.strip():
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn.strip(),
        environment=settings.sentry_environment or "local",
        release=settings.sentry_release.strip() or None,
        traces_sample_rate=0.0,
        send_default_pii=False,
        max_request_body_size="never",
        event_scrubber=EventScrubber(denylist=_SENTRY_DENYLIST),
    )
    _sentry_enabled = True
    logger.info(
        "sentry enabled",
        extra={
            "environment": settings.sentry_environment or "local",
            "release": settings.sentry_release.strip() or None,
        },
    )
    return True


def sentry_enabled() -> bool:
    """Truth for the health readout (``sentry_sdk.is_initialized()`` lies —
    it reports True for a disabled DSN-less client too)."""
    return _sentry_enabled


def capture_job_failure(
    exc: BaseException,
    *,
    job_id: Any,
    stage: str,
    error_type: str,
    platform: str | None,
    attempt: int,
) -> None:
    """One Sentry issue per TERMINAL job failure, tagged with the job context
    the plan demands (job id + stage + error_type). Safe uninitialised."""
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("job_id", str(job_id))
        scope.set_tag("stage", stage)
        scope.set_tag("error_type", error_type)
        scope.set_tag("platform", platform or "unknown")
        scope.set_tag("attempt", attempt)
        sentry_sdk.capture_exception(exc)


def add_job_breadcrumb(message: str, *, job_id: Any, **data: Any) -> None:
    """Breadcrumb (NOT an issue) for non-terminal job events — retries and
    requeues annotate the eventual failure instead of paging on their own."""
    sentry_sdk.add_breadcrumb(
        category="job",
        message=message,
        level="warning",
        data={"job_id": str(job_id), **data},
    )


def capture_budget_alert(message: str, pct: int) -> None:
    """Budget threshold crossings become Sentry messages: 80% warns, 100% is
    an error (paid calls stop there — that is worth paging over)."""
    sentry_sdk.capture_message(message, level="error" if pct >= 100 else "warning")
