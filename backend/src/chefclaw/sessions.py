"""Server-side opaque sessions (M2, ADR 2026-07-07-m2-accounts-and-invites).

The cookie carries a random 256-bit token; only its sha256 is stored, so a DB
dump can't be replayed as live cookies. ``resolve_owner`` returns the owner only
for an UNEXPIRED session whose user is still ``active`` (a de-invited/booted user
stops resolving instantly). Revocation (logout) is a row DELETE — the reason
this is stateful, not a JWT.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chefclaw.models import Session, User, UserStatus

# Only rewrite last_seen_at when it is at least this stale — an authed request
# must not write a row on every hit (critique M8 perf note).
_LAST_SEEN_THROTTLE = timedelta(minutes=5)


def hash_token(raw_token: str) -> str:
    """sha256 hex of a raw cookie token — what we store, never the raw value.
    Shared by sessions and (PR 3) invite tokens."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def new_session_token() -> str:
    """A fresh opaque 256-bit session token (raw — only its hash is stored)."""
    return secrets.token_urlsafe(32)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def create_session(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_id: uuid.UUID,
    *,
    ttl_hours: int,
    now: datetime | None = None,
) -> str:
    """Mint a session for ``owner_id`` and return the RAW cookie token (only its
    sha256 lands in the row). Absolute expiry = now + ttl_hours."""
    now = now or datetime.now(UTC)
    raw = new_session_token()
    row = Session(
        owner_id=owner_id,
        token_hash=hash_token(raw),
        expires_at=now + timedelta(hours=ttl_hours),
    )
    async with sessionmaker() as session, session.begin():
        session.add(row)
    return raw


async def resolve_owner(
    sessionmaker: async_sessionmaker[AsyncSession],
    token_hash: str,
    *,
    idle_timeout_hours: int | None = None,
    now: datetime | None = None,
) -> uuid.UUID | None:
    """The owner behind a LIVE session whose user is still active, else None.
    Live = unexpired (absolute ``expires_at``) AND — when ``idle_timeout_hours``
    is set and > 0 — used within the idle window (``last_seen_at`` newer than
    now - idle_timeout). Bumps last_seen_at only when it is stale (throttled —
    critique M8), which is what makes the idle window load-bearing (V2-D)."""
    now = now or datetime.now(UTC)
    conditions = [
        Session.token_hash == token_hash,
        Session.expires_at > now,
        User.status == UserStatus.ACTIVE.value,
    ]
    if idle_timeout_hours and idle_timeout_hours > 0:
        conditions.append(Session.last_seen_at > now - timedelta(hours=idle_timeout_hours))
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(Session.id, Session.owner_id, Session.last_seen_at)
                .join(User, User.id == Session.owner_id)
                .where(*conditions)
                .limit(1)
            )
        ).first()
    if row is None:
        return None
    session_id, owner_id, last_seen_at = row
    if last_seen_at is None or (now - _aware(last_seen_at)) > _LAST_SEEN_THROTTLE:
        async with sessionmaker() as session, session.begin():
            await session.execute(
                update(Session).where(Session.id == session_id).values(last_seen_at=now)
            )
    return owner_id


async def delete_session(
    sessionmaker: async_sessionmaker[AsyncSession], token_hash: str
) -> None:
    """Revoke a session (logout) — instant, server-side."""
    async with sessionmaker() as session, session.begin():
        await session.execute(delete(Session).where(Session.token_hash == token_hash))
