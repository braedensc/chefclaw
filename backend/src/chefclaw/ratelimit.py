"""Per-session / per-IP request throttle (V2-D security audit).

No request throttle existed before this: a session (or, pre-M2, a bearer token)
holder could make unlimited requests. This adds the kit's append-only-event
pattern (docs/SECURITY.md) — one ``request_events`` row per served request, the
trailing-window COUNT over a coarse identity key IS the limit. No mutable counter
to race, no cron to reset.

Two buckets, picked by whether a session cookie is present:
- **authenticated** — keyed per SESSION (``session:<sha256(cookie)>``): the backstop
  against a runaway/compromised session. Generous by default (real browsing bursts
  image loads); it stops abuse, not normal use.
- **public** — keyed per client IP (``ip:<addr>``): covers the pre-auth endpoints the
  audit called out — ``/api/auth/google/callback`` and ``/api/invites/{token}`` — so
  neither the OAuth callback nor invite-token lookups can be hammered.

Fail-OPEN by design: a limiter DB error allows the request (the limiter must never
take the app down; ``require_owner`` already 503s on a real DB outage). Set in the
LIFESPAN (not ``create_app``), so the unit tier — which runs under ASGITransport with
no lifespan and no DB — never has a limiter and is never throttled; DB-tier tests
drive ``PostgresRateLimiter`` directly, and unit tests inject a fake onto
``app.state.rate_limiter``.

Residual (V2-D ADR): the client IP is ``scope['client']`` — the direct peer. A future
reverse proxy (Caddy/Traefik for public TLS) terminates that, so the public bucket
would then need a trusted-proxy X-Forwarded-For read. Same-origin Tailscale today has
no such hop.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from chefclaw.auth import SESSION_COOKIE_NAME
from chefclaw.models import RequestEvent
from chefclaw.sessions import hash_token

logger = logging.getLogger(__name__)


class RateLimitRule(NamedTuple):
    """A trailing-window cap: at most ``limit`` served requests per key within
    the last ``window_seconds``. ``limit <= 0`` disables the bucket."""

    limit: int
    window_seconds: int


class PostgresRateLimiter:
    """Append-only rate limiter over ``request_events``. One instance holds both
    bucket rules; ``check_and_record`` is called per request with the resolved key
    and rule."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        authenticated_rule: RateLimitRule,
        public_rule: RateLimitRule,
    ) -> None:
        self._sm = sessionmaker
        self.authenticated_rule = authenticated_rule
        self.public_rule = public_rule

    async def check_and_record(
        self, key: str, rule: RateLimitRule, *, now: datetime | None = None
    ) -> bool:
        """True if the request is UNDER the limit (and record it); False if it
        would exceed the trailing-window cap (record nothing — a rejected request
        isn't a served one). An advisory xact lock serializes concurrent checks
        for the SAME key so count-then-insert can't over-admit under a burst; a
        rejected request never gets a row."""
        now = now or datetime.now(UTC)
        window_start = now - timedelta(seconds=rule.window_seconds)
        async with self._sm() as session, session.begin():
            # Per-key advisory lock (released at commit): no table lock, no mutable
            # counter — just serialize this key's count→insert against a burst.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key}
            )
            count = await session.scalar(
                select(func.count())
                .select_from(RequestEvent)
                .where(RequestEvent.key == key, RequestEvent.created_at > window_start)
            )
            if count is not None and count >= rule.limit:
                return False
            session.add(RequestEvent(key=key, created_at=now))
            # Opportunistic prune keeps each key's rows bounded to ~one window —
            # append-only stays append-only, but never grows without bound.
            await session.execute(
                delete(RequestEvent).where(
                    RequestEvent.key == key, RequestEvent.created_at <= window_start
                )
            )
            return True


class RateLimitMiddleware:
    """Pure-ASGI throttle for ``/api/*``. Skips entirely when no limiter is on
    ``app.state`` (the unit tier). Picks the bucket by the presence of the session
    cookie, fails open on any limiter error, and returns the typed ``rate_limited``
    error body (HTTP 429 + Retry-After) on a breach."""

    def __init__(self, app: object) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api"):
            await self.app(scope, receive, send)
            return
        limiter: PostgresRateLimiter | None = getattr(
            scope["app"].state, "rate_limiter", None
        )
        if limiter is None:
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if cookie:
            key = f"session:{hash_token(cookie)}"
            rule = limiter.authenticated_rule
        else:
            client = request.client
            key = f"ip:{client.host if client else 'unknown'}"
            rule = limiter.public_rule

        if rule.limit <= 0:  # bucket disabled
            await self.app(scope, receive, send)
            return

        try:
            allowed = await limiter.check_and_record(key, rule)
        except Exception:
            # Fail OPEN: the limiter must never take the app down. A real DB
            # outage already surfaces as a 503 from require_owner.
            logger.warning("rate limiter check failed — allowing (fail-open)", exc_info=True)
            allowed = True

        if not allowed:
            from fastapi.responses import JSONResponse

            response = JSONResponse(
                status_code=429,
                content={
                    "error_type": "rate_limited",
                    "detail": "Too many requests — slow down and retry shortly.",
                },
                headers={"Retry-After": str(rule.window_seconds)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
