"""User administration service.

Two admin surfaces, both behind transport-layer ``require_admin`` (critique M9 —
identity/admin status are never settable here):

- **Per-user cost controls (M3, ADR 2026-07-07-per-user-budget-caps):** the cap
  setter updates the nullable ``users`` cap columns the paid-call gate
  (:func:`chefclaw.spend.check_budget`) reads (NULL = use the global env
  default) plus the ``paid_tier`` flag.
- **Private real-frame grant (V2-F):** the owner lists members and toggles each
  one's ``real_covers_enabled``.
"""

import uuid
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chefclaw.models import User

__all__ = [
    "UserBudgetRow",
    "list_users",
    "read_paid_tier",
    "set_real_covers_enabled",
    "set_user_budget",
]

Sm = async_sessionmaker[AsyncSession]

_CENT = Decimal("0.01")  # matches users.monthly_budget_usd numeric(10,2)


class UserBudgetRow(NamedTuple):
    """The per-user cost controls the admin API returns after a write. NULL caps
    = no per-user override (the global env cap applies); ``paid_tier`` false =
    the global GEMINI_MODEL (free) default."""

    id: uuid.UUID
    email: str
    monthly_budget_usd: Decimal | None
    max_attempts_per_day: int | None
    paid_tier: bool


async def read_paid_tier(session: AsyncSession, owner_id: uuid.UUID) -> bool:
    """Whether this account is on the paid Gemini tier (M3). False when no row
    exists — the safe/cheap default (the worker then uses the global model)."""
    value = await session.scalar(select(User.paid_tier).where(User.id == owner_id))
    return bool(value)


async def set_user_budget(
    sm: Sm,
    user_id: uuid.UUID,
    *,
    values: dict[str, float | int | bool | None],
) -> UserBudgetRow | None:
    """Set (or clear) a user's per-user cost controls in ONE transaction.
    ``values`` is a PARTIAL map (only the keys the request sent): a key present
    with a value sets it, a cap present with ``None`` clears it back to the
    global env cap; an absent key is left untouched. The monthly amount is
    quantized to the cent (the ``numeric(10,2)`` column). Returns the updated
    row, or None when no user has ``user_id`` (⇒ 404 at the transport layer)."""
    async with sm() as s, s.begin():
        user = (
            await s.execute(select(User).where(User.id == user_id).with_for_update())
        ).scalars().first()
        if user is None:
            return None
        if "monthly_budget_usd" in values:
            raw = values["monthly_budget_usd"]
            user.monthly_budget_usd = (
                Decimal(str(raw)).quantize(_CENT) if raw is not None else None
            )
        if "max_attempts_per_day" in values:
            user.max_attempts_per_day = values["max_attempts_per_day"]
        # paid_tier is a plain flag (not a cap): send true/false. A null is a
        # no-op — there is no 'clear to global' for a boolean.
        if values.get("paid_tier") is not None:
            user.paid_tier = bool(values["paid_tier"])
        await s.flush()
        return UserBudgetRow(
            id=user.id,
            email=user.email,
            monthly_budget_usd=user.monthly_budget_usd,
            max_attempts_per_day=user.max_attempts_per_day,
            paid_tier=user.paid_tier,
        )


async def list_users(sm: async_sessionmaker[AsyncSession]) -> list[User]:
    """Every account, oldest first (the owner is the seed row)."""
    async with sm() as session:
        return list((await session.execute(select(User).order_by(User.created_at))).scalars().all())


async def set_real_covers_enabled(
    sm: async_sessionmaker[AsyncSession], user_id: uuid.UUID, enabled: bool
) -> User | None:
    """Set one member's private real-frame grant (V2-F). Returns the updated
    user, or ``None`` when no such user exists (→ 404)."""
    async with sm() as session:
        user = await session.get(User, user_id)
        if user is None:
            return None
        user.real_covers_enabled = enabled
        await session.commit()
        await session.refresh(user)
        return user
