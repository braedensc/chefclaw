"""Cookie-session auth behind ONE swappable FastAPI dependency (M2).

Routers depend only on ``require_owner`` — its signature stays ``-> uuid.UUID``
and it still sets ``request.state.owner_id``; only its INTERNALS changed, from a
bearer token to an opaque server-side session cookie (ADR
2026-07-07-m2-accounts-and-invites). ``require_admin`` layers on top for the
admin surface (critique M9). The old ``_cached_owner_id`` process singleton is
GONE — it pinned one owner per process, a cross-tenant bug under M2.

Two-tier posture, mirroring the extractor seam:
- ``chefclaw_auth_provider="fake"`` (default) — require_owner SHORT-CIRCUITS to
  ``chefclaw_fake_owner_id`` (no cookie/session read), so the unit tier needs no
  DB. It refuses to run if a real Google client id is ALSO set (the operator
  staged creds but forgot to flip the provider — critique M7 guard 2).
- ``google`` — require_owner reads the ``chefclaw_session`` cookie, hashes it,
  and resolves the owner via ``fetch_session_owner_id`` (stubbable in tests).
"""

import uuid
from typing import Annotated, NamedTuple

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from chefclaw import db, sessions
from chefclaw.config import Settings, get_settings
from chefclaw.errors import ConfigError
from chefclaw.models import User

SESSION_COOKIE_NAME = "chefclaw_session"

_VALID_AUTH_PROVIDERS = ("fake", "google")


class Account(NamedTuple):
    """The identity slice GET /api/me returns. ``is_admin`` is server-derived —
    NEVER settable via a user-facing write (critique M9)."""

    id: uuid.UUID
    name: str
    email: str
    is_admin: bool


def assert_prod_auth_safe(settings: Settings) -> None:
    """Fail the boot CLOSED on an unsafe auth config (critique M7 — called from
    create_app). Three checks:

    1. an unknown provider selector (M7 guard 3);
    2. the fake provider WITH a real Google client id staged — flip the provider
       (M7 guard 2, startup form);
    3. a 'vps' (prod) environment with the fake provider — an unset/typo'd env
       must never silently authenticate everyone as one owner (M7 guard 1).

    (PR 3 extends this with the email-provider checks.)"""
    provider = settings.chefclaw_auth_provider
    if provider not in _VALID_AUTH_PROVIDERS:
        raise ConfigError(
            f"Unknown CHEFCLAW_AUTH_PROVIDER {provider!r} — expected 'fake' or 'google'."
        )
    if provider == "fake" and settings.google_oauth_client_id:
        raise ConfigError(
            "CHEFCLAW_AUTH_PROVIDER=fake but GOOGLE_OAUTH_CLIENT_ID is set — refusing "
            "to fake-auth with real OAuth creds staged (set CHEFCLAW_AUTH_PROVIDER=google)."
        )
    if provider == "fake" and settings.sentry_environment == "vps":
        raise ConfigError(
            "CHEFCLAW_AUTH_PROVIDER=fake in a 'vps' (prod) environment — refusing to "
            "start: fake auth authenticates everyone as one owner. Set "
            "CHEFCLAW_AUTH_PROVIDER=google."
        )
    if provider == "google" and not (
        settings.google_oauth_client_id and settings.google_oauth_client_secret
    ):
        # Fail the boot rather than 500 at the first login (fail-fast; the same
        # empty-creds rule get_oauth_provider enforces at request time).
        raise ConfigError(
            "CHEFCLAW_AUTH_PROVIDER=google but GOOGLE_OAUTH_CLIENT_ID/SECRET is empty "
            "— no OAuth without explicit credentials (fail-closed)."
        )
    # Email provider (PR 3): the same fake-in-prod footgun as auth (M7).
    if settings.chefclaw_email not in ("fake", "ses"):
        raise ConfigError(
            f"Unknown CHEFCLAW_EMAIL {settings.chefclaw_email!r} — expected 'fake' or 'ses'."
        )
    if settings.chefclaw_email == "fake" and settings.sentry_environment == "vps":
        raise ConfigError(
            "CHEFCLAW_EMAIL=fake in a 'vps' (prod) environment — refusing to start: "
            "invite emails would only be logged, never sent. Set CHEFCLAW_EMAIL=ses."
        )


async def fetch_session_owner_id(token_hash: str) -> uuid.UUID | None:
    """Resolve the owner behind a session cookie's sha256. Stubbed in the unit
    tier (no DB); the real path delegates to sessions.resolve_owner."""
    return await sessions.resolve_owner(db.get_sessionmaker(), token_hash)


async def fetch_account(owner_id: uuid.UUID) -> "Account | None":
    """The GET /api/me + require_admin identity row. Stubbed in the unit tier."""
    async with db.get_sessionmaker()() as session:
        row = (
            await session.execute(
                select(User.id, User.name, User.email, User.is_admin).where(User.id == owner_id)
            )
        ).first()
    if row is None:
        return None
    return Account(row.id, row.name, row.email, row.is_admin)


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated — sign in.",
    )


async def require_owner(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> uuid.UUID:
    """Resolve the authenticated owner id. Contract unchanged: ``-> uuid.UUID``,
    sets ``request.state.owner_id`` (the request log reads it off the scope)."""
    if settings.chefclaw_auth_provider == "fake":
        # Defense in depth (critique M7 guard 2): a real client id + fake
        # provider is a misconfig — refuse rather than silently fake-auth.
        if settings.google_oauth_client_id:
            raise ConfigError(
                "chefclaw_auth_provider=fake but google_oauth_client_id is set — refusing "
                "to fake-auth with real OAuth creds staged."
            )
        owner_id = uuid.UUID(settings.chefclaw_fake_owner_id)
        request.state.owner_id = owner_id
        return owner_id

    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        raise _unauthenticated()
    try:
        owner_id = await fetch_session_owner_id(sessions.hash_token(raw))
    except Exception as exc:  # DB unreachable while resolving the session
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unreachable while resolving the session.",
        ) from exc
    if owner_id is None:
        raise _unauthenticated()
    request.state.owner_id = owner_id
    return owner_id


async def require_admin(
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
) -> uuid.UUID:
    """Layer on ``require_owner`` for the admin surface (critique M9): the owner
    must be ``is_admin``, enforced at the TRANSPORT layer (the frontend
    ``me.is_admin`` gate is cosmetic only). Returns the owner id on success,
    403 otherwise."""
    account = await fetch_account(owner_id)
    if account is None or not account.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return owner_id
