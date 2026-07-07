"""GOLDEN invites tier (`-m golden`): the real invite SQL — issue/rotate,
consume (account create + accept in one tx), bootstrap-claim, revoke, the M13
public shape, and the callback end-to-end — against a throwaway postgres. Needs
the same throwaway PG as test_worker_db.py (127.0.0.1:55432).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chefclaw import db, sessions
from chefclaw.config import Settings
from chefclaw.models import Base, Invite, Session, User
from chefclaw.oauth import FakeOAuthProvider, VerifiedIdentity
from chefclaw.services import invites
from tests.conftest import make_app

pytestmark = pytest.mark.golden

GOLDEN_DB_URL = "postgresql+asyncpg://chefclaw@127.0.0.1:55432/chefclaw_golden"


@pytest.fixture
async def sm():
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


def _settings(**overrides) -> Settings:
    base = dict(chefclaw_auth_provider="fake", public_base_url="http://x", invite_ttl_hours=168)
    base.update(overrides)
    return Settings(**base)


async def _seed_admin(sm) -> uuid.UUID:
    """A seed admin with oauth NULL — mirrors the migration backfill."""
    async with sm() as s:
        u = User(name="owner", email="owner@localhost", is_admin=True)
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id


# ── issue / rotate ────────────────────────────────────────────────────────────


async def test_issue_and_rotate_invite(sm) -> None:
    admin = await _seed_admin(sm)
    row1, raw1, new1 = await invites.issue_invite(
        sm, _settings(), invited_by=admin, email="Friend@X.com"
    )
    assert new1 is True
    assert row1.email == "friend@x.com"  # normalized (lower/strip)
    # A second issue for the same email ROTATES the one pending row (new token).
    row2, raw2, new2 = await invites.issue_invite(
        sm, _settings(), invited_by=admin, email="friend@x.com"
    )
    assert new2 is False
    assert row2.id == row1.id
    assert raw2 != raw1
    async with sm() as s:
        count = await s.scalar(select(func.count(Invite.id)))
    assert count == 1  # partial-unique: exactly one pending invite per email


# ── consume (account create + accept, one tx) ─────────────────────────────────


async def test_consume_invite_creates_user_and_is_single_use(sm) -> None:
    admin = await _seed_admin(sm)
    await invites.issue_invite(sm, _settings(), invited_by=admin, email="newbie@x.com")
    ident = VerifiedIdentity("google", "sub-x", "Newbie@X.com", True, "Newbie")

    owner_id = await invites.activate_identity(sm, _settings(), ident)
    assert owner_id is not None
    async with sm() as s:
        user = await s.get(User, owner_id)
        inv = (await s.execute(select(Invite))).scalars().one()
    assert user.email == "newbie@x.com"
    assert (user.oauth_provider, user.oauth_subject) == ("google", "sub-x")
    assert user.is_admin is False  # invitees are never admin
    assert inv.status == "accepted"
    assert inv.accepted_user_id == owner_id
    # Single-use: a second activation finds no pending invite (→ opaque 403).
    assert await invites.activate_identity(sm, _settings(), ident) is None


async def test_activation_without_invite_or_bootstrap_is_none(sm) -> None:
    await _seed_admin(sm)
    ident = VerifiedIdentity("google", "s", "stranger@x.com", True, None)
    # No invite, bootstrap disabled (empty email) ⇒ None (the callback's 403).
    assert await invites.activate_identity(sm, _settings(bootstrap_admin_email=""), ident) is None


# ── bootstrap-claim (M6b) ─────────────────────────────────────────────────────


async def test_bootstrap_claim_adopts_seed_admin(sm) -> None:
    admin_id = await _seed_admin(sm)
    ident = VerifiedIdentity("google", "braeden-sub", "Braeden@Gmail.com", True, "Braeden")
    settings = _settings(bootstrap_admin_email="braeden@gmail.com")

    owner_id = await invites.activate_identity(sm, settings, ident)
    assert owner_id == admin_id  # the SEED row was adopted, not a new user
    async with sm() as s:
        seed = await s.get(User, admin_id)
        user_count = await s.scalar(select(func.count(User.id)))
    assert (seed.oauth_provider, seed.oauth_subject) == ("google", "braeden-sub")
    assert seed.email == "braeden@gmail.com"  # normalized
    assert seed.is_admin is True
    assert user_count == 1  # adopted, not created

    # A SECOND bootstrap attempt: the seed is already claimed (oauth non-null),
    # so there is no unclaimed admin row ⇒ None (no second admin can be minted).
    again = VerifiedIdentity("google", "other-sub", "braeden@gmail.com", True, None)
    assert await invites.activate_identity(sm, settings, again) is None


async def test_bootstrap_disabled_when_email_mismatches(sm) -> None:
    await _seed_admin(sm)
    # bootstrap_admin_email set, but the verified email is someone ELSE ⇒ no
    # claim (and no invite) ⇒ None. Kills the "first stranger becomes admin" race.
    ident = VerifiedIdentity("google", "s", "stranger@x.com", True, None)
    settings = _settings(bootstrap_admin_email="braeden@gmail.com")
    assert await invites.activate_identity(sm, settings, ident) is None


# ── revoke ────────────────────────────────────────────────────────────────────


async def test_revoke_outcomes(sm) -> None:
    admin = await _seed_admin(sm)
    row, _, _ = await invites.issue_invite(sm, _settings(), invited_by=admin, email="a@x.com")
    assert await invites.revoke_invite(sm, row.id) == "revoked"
    assert await invites.revoke_invite(sm, row.id) == "revoked"  # idempotent
    assert await invites.revoke_invite(sm, uuid.uuid4()) == "not_found"

    inv2, _, _ = await invites.issue_invite(sm, _settings(), invited_by=admin, email="b@x.com")
    await invites.activate_identity(
        sm, _settings(), VerifiedIdentity("google", "s2", "b@x.com", True, None)
    )
    assert await invites.revoke_invite(sm, inv2.id) == "already_accepted"


# ── public invite shape (M13) ─────────────────────────────────────────────────


async def test_public_invite_shapes(sm) -> None:
    admin = await _seed_admin(sm)
    row, raw, _ = await invites.issue_invite(sm, _settings(), invited_by=admin, email="p@x.com")
    # Live pending ⇒ reveals the email.
    assert await invites.public_invite(sm, raw) == invites.PublicInvite("pending", "p@x.com")
    # Missing token ⇒ uniform 'invalid', no email.
    assert await invites.public_invite(sm, "nope") == invites.PublicInvite("invalid", None)
    # Revoked ⇒ same 'invalid' shape (no address leak).
    await invites.revoke_invite(sm, row.id)
    assert await invites.public_invite(sm, raw) == invites.PublicInvite("invalid", None)
    # Expired ⇒ same 'invalid' shape.
    async with sm() as s:
        s.add(
            Invite(
                email="e@x.com",
                token_hash=sessions.hash_token("exp-tok"),
                status="pending",
                invited_by=admin,
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await s.commit()
    assert await invites.public_invite(sm, "exp-tok") == invites.PublicInvite("invalid", None)


# ── callback end-to-end (invite gate + session insert, real SQL) ──────────────


async def test_callback_consumes_invite_end_to_end(sm, monkeypatch) -> None:
    """The design's golden posture: the fake provider bypasses ONLY Google's
    network; the callback's invite consume + user create + session insert run
    against REAL SQL."""
    monkeypatch.setattr(db, "get_sessionmaker", lambda: sm)
    admin = await _seed_admin(sm)
    ident = FakeOAuthProvider.identity
    await invites.issue_invite(sm, _settings(), invited_by=admin, email=ident.email)

    app = make_app()  # fake provider; bootstrap_admin_email default "" ⇒ invite path
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.get("/api/auth/google/login", follow_redirects=False)
        callback = await client.get(login.headers["location"], follow_redirects=False)

    assert callback.status_code == 302
    async with sm() as s:
        new_user = (
            await s.execute(select(User).where(User.email == ident.email))
        ).scalars().one()
        session_count = await s.scalar(select(func.count(Session.id)))
        inv = (await s.execute(select(Invite))).scalars().one()
    assert new_user.is_admin is False
    assert (new_user.oauth_provider, new_user.oauth_subject) == (ident.provider, ident.subject)
    assert session_count == 1
    assert inv.status == "accepted"
    assert inv.accepted_user_id == new_user.id


# ── DB-enforced TTL on consume (V2-D) ─────────────────────────────────────────


async def test_consume_expired_invite_is_none(sm) -> None:
    """An expired pending invite cannot be consumed — the consume path filters
    (and the UPDATE guards) on expires_at > now(), so activation returns None
    (→ opaque 403) and creates no user."""
    admin = await _seed_admin(sm)
    # invite_ttl_hours negative ⇒ issued already-expired.
    await invites.issue_invite(
        sm, _settings(invite_ttl_hours=-1), invited_by=admin, email="late@x.com"
    )
    ident = VerifiedIdentity("google", "sub-late", "late@x.com", True, "Late")
    assert await invites.activate_identity(sm, _settings(), ident) is None
    async with sm() as s:
        users = await s.scalar(select(func.count(User.id)))
    assert users == 1  # only the seed admin — no account created
