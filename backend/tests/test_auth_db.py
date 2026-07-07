"""GOLDEN auth tier (`-m golden`): the real session + callback SQL against a
throwaway postgres — what the fakes/stubs cannot exercise. Needs the same
throwaway PG as test_worker_db.py (127.0.0.1:55432); see that module's docstring
for the docker run command.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chefclaw import auth, db, sessions
from chefclaw.models import Base, Session, User
from chefclaw.oauth import FakeOAuthProvider, VerifiedIdentity
from chefclaw.routers.auth import resolve_owner_by_identity
from tests.conftest import make_app

pytestmark = pytest.mark.golden

GOLDEN_DB_URL = "postgresql+asyncpg://chefclaw@127.0.0.1:55432/chefclaw_golden"


@pytest.fixture
async def sessionmaker():
    engine = create_async_engine(GOLDEN_DB_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment guard
        await engine.dispose()
        pytest.skip(f"throwaway postgres not reachable on 127.0.0.1:55432 ({exc})")
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed_user(sm, **overrides) -> uuid.UUID:
    fields = dict(name="owner", email="owner@localhost", status="active")
    fields.update(overrides)
    async with sm() as session:
        user = User(**fields)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


# ── session lifecycle (real SQL) ──────────────────────────────────────────────


async def test_session_create_resolve_delete(sessionmaker) -> None:
    owner_id = await _seed_user(sessionmaker)
    raw = await sessions.create_session(sessionmaker, owner_id, ttl_hours=1)

    # The RAW token is never stored — only its sha256.
    async with sessionmaker() as s:
        stored = (await s.execute(select(Session.token_hash))).scalar_one()
    assert stored == sessions.hash_token(raw)
    assert stored != raw

    assert await sessions.resolve_owner(sessionmaker, sessions.hash_token(raw)) == owner_id
    # A wrong hash resolves to nothing.
    assert await sessions.resolve_owner(sessionmaker, sessions.hash_token("other")) is None

    await sessions.delete_session(sessionmaker, sessions.hash_token(raw))
    assert await sessions.resolve_owner(sessionmaker, sessions.hash_token(raw)) is None


async def test_expired_session_does_not_resolve(sessionmaker) -> None:
    owner_id = await _seed_user(sessionmaker)
    raw = await sessions.create_session(sessionmaker, owner_id, ttl_hours=1)
    # Resolve with a 'now' past the absolute expiry.
    future = datetime.now(UTC) + timedelta(hours=2)
    assert await sessions.resolve_owner(sessionmaker, sessions.hash_token(raw), now=future) is None


async def test_disabled_user_session_does_not_resolve(sessionmaker) -> None:
    """A de-invited/booted (disabled) user's sessions stop resolving instantly —
    the server-side revocation the whole stateful design exists for."""
    owner_id = await _seed_user(sessionmaker, status="disabled")
    raw = await sessions.create_session(sessionmaker, owner_id, ttl_hours=1)
    assert await sessions.resolve_owner(sessionmaker, sessions.hash_token(raw)) is None


# ── resolve_owner_by_identity (real SQL) ──────────────────────────────────────


async def test_resolve_owner_by_identity(sessionmaker, monkeypatch) -> None:
    monkeypatch.setattr(db, "get_sessionmaker", lambda: sessionmaker)
    bound = await _seed_user(
        sessionmaker, oauth_provider="google", oauth_subject="sub-123", email="bound@x"
    )
    ident = VerifiedIdentity("google", "sub-123", "bound@x", True, "Bound")
    assert await resolve_owner_by_identity(ident) == bound
    # An unknown subject binds to nobody.
    unknown = VerifiedIdentity("google", "nope", "x@x", True, None)
    assert await resolve_owner_by_identity(unknown) is None


# ── callback end-to-end (real session insert, fake provider) ──────────────────


async def test_callback_creates_real_session_for_returning_user(sessionmaker, monkeypatch) -> None:
    """The fake provider bypasses ONLY Google's network; the callback's user
    resolution + session insert run against REAL SQL (the design's golden
    posture). A user bound to the FakeOAuthProvider identity gets a real
    session row."""
    monkeypatch.setattr(db, "get_sessionmaker", lambda: sessionmaker)
    ident = FakeOAuthProvider.identity
    owner_id = await _seed_user(
        sessionmaker,
        oauth_provider=ident.provider,
        oauth_subject=ident.subject,
        email=ident.email,
    )

    app = make_app()  # fake provider; require_owner short-circuit is irrelevant here
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.get("/api/auth/google/login", follow_redirects=False)
        callback = await client.get(login.headers["location"], follow_redirects=False)

    assert callback.status_code == 302
    assert auth.SESSION_COOKIE_NAME in "; ".join(callback.headers.get_list("set-cookie"))
    # Exactly one real session row, owned by the returning user.
    async with sessionmaker() as s:
        count = await s.scalar(select(func.count(Session.id)))
        row_owner = await s.scalar(select(Session.owner_id))
    assert count == 1
    assert row_owner == owner_id


async def test_callback_unbound_identity_creates_no_session(sessionmaker, monkeypatch) -> None:
    """No user bound to the identity ⇒ opaque 403 with NO session row (fail
    closed, no side effects — critique M6)."""
    monkeypatch.setattr(db, "get_sessionmaker", lambda: sessionmaker)
    await _seed_user(sessionmaker)  # a user, but NOT bound to the fake identity

    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.get("/api/auth/google/login", follow_redirects=False)
        callback = await client.get(login.headers["location"], follow_redirects=False)

    assert callback.status_code == 403
    async with sessionmaker() as s:
        count = await s.scalar(select(func.count(Session.id)))
    assert count == 0  # no side effects


# ── idle timeout (V2-D) ───────────────────────────────────────────────────────


async def test_idle_session_stops_resolving_before_absolute_expiry(sessionmaker) -> None:
    """last_seen_at becomes load-bearing (V2-D): a session unused longer than the
    idle window stops resolving even while its absolute expires_at is far in the
    future — and idle_timeout_hours=0 disables the check (absolute TTL only)."""
    owner_id = await _seed_user(sessionmaker)
    raw = await sessions.create_session(sessionmaker, owner_id, ttl_hours=720)  # 30d absolute
    h = sessions.hash_token(raw)

    # Fresh session, within the idle window ⇒ resolves.
    assert await sessions.resolve_owner(sessionmaker, h, idle_timeout_hours=24) == owner_id

    # 48h later with a 24h idle window: last_seen_at is stale ⇒ does NOT resolve
    # (checked BEFORE the throttled last_seen bump, so the idle row is excluded).
    future = datetime.now(UTC) + timedelta(hours=48)
    assert (
        await sessions.resolve_owner(sessionmaker, h, idle_timeout_hours=24, now=future) is None
    )
    # Idle check disabled ⇒ the same still-unexpired session resolves.
    assert (
        await sessions.resolve_owner(sessionmaker, h, idle_timeout_hours=0, now=future) == owner_id
    )
