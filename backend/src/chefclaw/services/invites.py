"""Invite issuance + activation (M2 PR 3, ADR 2026-07-07-m2-accounts-and-invites).

Invite-only signup: an admin issues an invite for an email; an OAuth sign-in with
a matching VERIFIED email consumes it (creating the account) in ONE transaction.
The raw token is returned to the caller ONCE (to build the activation link) and
NEVER stored — only its sha256. First-owner bootstrap-claim adopts the migration-
seeded admin row, gated on ``bootstrap_admin_email`` (critique M6b).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chefclaw.config import Settings
from chefclaw.models import Invite, InviteStatus, User, UserStatus
from chefclaw.oauth import VerifiedIdentity
from chefclaw.sessions import hash_token, new_session_token

Sm = async_sessionmaker[AsyncSession]

RevokeOutcome = Literal["revoked", "already_accepted", "not_found"]


def normalize_email(raw: str) -> str:
    """lower + strip. NO gmail dot-stripping (critique M5) — applied identically
    to the invite email at create and the OAuth email at match, so the two sides
    can never diverge on normalization."""
    return raw.strip().lower()


class InviteRow(NamedTuple):
    """The invite slice the API returns — NEVER the token_hash (critique)."""

    id: uuid.UUID
    email: str
    status: str
    expires_at: datetime
    created_at: datetime
    accepted_at: datetime | None


class PublicInvite(NamedTuple):
    """The public invite-accept shape (M13). ``status`` is 'pending' | 'invalid';
    ``email`` is revealed ONLY for a live pending invite."""

    status: str
    email: str | None


def _row(inv: Invite) -> InviteRow:
    return InviteRow(
        inv.id, inv.email, inv.status, inv.expires_at, inv.created_at, inv.accepted_at
    )


async def active_member_exists(sm: Sm, email: str) -> bool:
    """True if a normalized email already belongs to an active account (an
    already-a-member re-invite is a 409, not a rotate)."""
    async with sm() as s:
        found = await s.scalar(
            select(User.id)
            .where(User.email == normalize_email(email), User.status == UserStatus.ACTIVE.value)
            .limit(1)
        )
    return found is not None


async def issue_invite(
    sm: Sm, settings: Settings, *, invited_by: uuid.UUID, email: str
) -> tuple[InviteRow, str, bool]:
    """Create OR rotate the pending invite for ``email`` in one transaction.
    Returns (row, raw_token, is_new). Rotating an existing pending invite resets
    its token + expiry (a resend). The raw token is returned ONCE (for the
    activation link); only its sha256 is stored."""
    email = normalize_email(email)
    raw = new_session_token()
    token_hash = hash_token(raw)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.invite_ttl_hours)
    async with sm() as s, s.begin():
        existing = (
            await s.execute(
                select(Invite)
                .where(Invite.email == email, Invite.status == InviteStatus.PENDING.value)
                .with_for_update()
            )
        ).scalars().first()
        if existing is not None:
            existing.token_hash = token_hash
            existing.expires_at = expires_at
            await s.flush()
            return _row(existing), raw, False
        inv = Invite(
            email=email,
            token_hash=token_hash,
            status=InviteStatus.PENDING.value,
            invited_by=invited_by,
            expires_at=expires_at,
        )
        s.add(inv)
        await s.flush()
        return _row(inv), raw, True


async def list_invites(sm: Sm, *, status: str | None = None) -> list[InviteRow]:
    stmt = select(Invite).order_by(Invite.created_at.desc())
    if status:
        stmt = stmt.where(Invite.status == status)
    async with sm() as s:
        rows = (await s.execute(stmt)).scalars().all()
    return [_row(r) for r in rows]


async def revoke_invite(sm: Sm, invite_id: uuid.UUID) -> RevokeOutcome:
    """Revoke a pending invite (idempotent: already-revoked → 'revoked'; an
    already-accepted invite is a 409; a missing one is a 404)."""
    async with sm() as s, s.begin():
        inv = await s.get(Invite, invite_id, with_for_update=True)
        if inv is None:
            return "not_found"
        if inv.status == InviteStatus.ACCEPTED.value:
            return "already_accepted"
        inv.status = InviteStatus.REVOKED.value
        return "revoked"


async def public_invite(sm: Sm, raw_token: str) -> PublicInvite:
    """The public invite-accept lookup (M13). Query by the indexed token_hash; a
    MISSING token and a present-but-expired/revoked/accepted invite return the
    SAME uniform 'invalid' shape (no enumeration oracle, no address leak). Only a
    live pending invite reveals the email."""
    now = datetime.now(UTC)
    async with sm() as s:
        inv = (
            await s.execute(
                select(Invite.email, Invite.status, Invite.expires_at)
                .where(Invite.token_hash == hash_token(raw_token))
                .limit(1)
            )
        ).first()
    if inv is None or inv.status != InviteStatus.PENDING.value or inv.expires_at <= now:
        return PublicInvite(status="invalid", email=None)
    return PublicInvite(status="pending", email=inv.email)


# ── activation (inside the OAuth callback) ────────────────────────────────────


async def activate_identity(
    sm: Sm, settings: Settings, identity: VerifiedIdentity
) -> uuid.UUID | None:
    """The callback gate for an UNBOUND verified identity: bootstrap-claim (gated
    on bootstrap_admin_email, M6b) OR consume a pending invite — each in ONE
    transaction. Returns the owner id, or None (→ opaque 403, M6)."""
    email = normalize_email(identity.email)
    boot = normalize_email(settings.bootstrap_admin_email)
    if boot and email == boot:
        claimed = await _claim_seed_admin(sm, identity, email)
        if claimed is not None:
            return claimed
    return await _consume_invite(sm, identity, email)


async def _claim_seed_admin(
    sm: Sm, identity: VerifiedIdentity, email: str
) -> uuid.UUID | None:
    """Bind the verified identity to the UNCLAIMED seed admin row (is_admin,
    oauth_provider IS NULL) in one transaction. Returns the id, or None if there
    is no unclaimed admin row (already bootstrapped)."""
    async with sm() as s, s.begin():
        seed = (
            await s.execute(
                select(User)
                .where(User.is_admin.is_(True), User.oauth_provider.is_(None))
                .order_by(User.created_at)
                .with_for_update()
                .limit(1)
            )
        ).scalars().first()
        if seed is None:
            return None
        seed.oauth_provider = identity.provider
        seed.oauth_subject = identity.subject
        seed.email = email
        seed.display_name = identity.name or seed.display_name
        await s.flush()
        return seed.id


async def _consume_invite(
    sm: Sm, identity: VerifiedIdentity, email: str
) -> uuid.UUID | None:
    """Consume a pending, unexpired invite for ``email``: create the account and
    flip the invite to accepted in ONE transaction. Single-use is enforced in
    the row lock + the WHERE status='pending' UPDATE rowcount (no TOCTOU)."""
    now = datetime.now(UTC)
    async with sm() as s, s.begin():
        invite = (
            await s.execute(
                select(Invite)
                .where(
                    Invite.email == email,
                    Invite.status == InviteStatus.PENDING.value,
                    Invite.expires_at > now,
                )
                .with_for_update()
                .limit(1)
            )
        ).scalars().first()
        if invite is None:
            return None
        user = User(
            name=identity.name or email,
            email=email,
            oauth_provider=identity.provider,
            oauth_subject=identity.subject,
            display_name=identity.name,
            status=UserStatus.ACTIVE.value,
            is_admin=False,
        )
        s.add(user)
        await s.flush()  # populate user.id
        # DB-enforced single-use + TTL (V2-D): the UPDATE itself carries the full
        # WHERE status='pending' AND expires_at > now() predicate, so single-use
        # holds at the datastore even independently of the FOR UPDATE lock above —
        # rowcount==1 is the atomic gate; anything else (already consumed / expired
        # under us) rolls the whole transaction back.
        result = await s.execute(
            update(Invite)
            .where(
                Invite.id == invite.id,
                Invite.status == InviteStatus.PENDING.value,
                Invite.expires_at > now,
            )
            .values(
                status=InviteStatus.ACCEPTED.value,
                accepted_user_id=user.id,
                accepted_at=now,
            )
        )
        if result.rowcount != 1:  # lost a race for this invite — roll back
            raise RuntimeError("invite consumed concurrently")
        return user.id
