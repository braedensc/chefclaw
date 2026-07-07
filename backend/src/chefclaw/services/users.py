"""User administration service (M3 per-user caps, ADR 2026-07-07-per-user-budget-caps).

The only write here is the admin cap setter: it updates the two nullable
``users`` cap columns the paid-call gate (:func:`chefclaw.spend.check_budget`)
reads. NULL on a column means 'use the global env default'; a positive value
overrides it for that account.
"""

import uuid
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chefclaw.models import User

Sm = async_sessionmaker[AsyncSession]

_CENT = Decimal("0.01")  # matches users.monthly_budget_usd numeric(10,2)


class UserBudgetRow(NamedTuple):
    """The per-user caps the admin API returns after a write. NULL = no
    per-user override (the global env cap applies)."""

    id: uuid.UUID
    email: str
    monthly_budget_usd: Decimal | None
    max_attempts_per_day: int | None


async def set_user_budget(
    sm: Sm,
    user_id: uuid.UUID,
    *,
    values: dict[str, float | int | None],
) -> UserBudgetRow | None:
    """Set (or clear) a user's per-user caps in ONE transaction. ``values`` is a
    PARTIAL map (only the keys the request sent): a key present with a number
    sets the override, present with ``None`` clears it back to the global env
    cap; an absent key is left untouched. The monthly amount is quantized to the
    cent (the ``numeric(10,2)`` column). Returns the updated row, or None when
    no user has ``user_id`` (⇒ 404 at the transport layer)."""
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
        await s.flush()
        return UserBudgetRow(
            id=user.id,
            email=user.email,
            monthly_budget_usd=user.monthly_budget_usd,
            max_attempts_per_day=user.max_attempts_per_day,
        )
