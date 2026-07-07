"""Admin user-management service (V2-F).

The owner lists members and toggles the per-user PRIVATE real-frame grant
(``real_covers_enabled``). That flag is the ONLY user-write this surface exposes
— identity, admin status, and caps are never settable here (critique M9). Every
caller sits behind ``require_admin`` at the transport layer.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chefclaw.models import User

__all__ = ["list_users", "set_real_covers_enabled"]


async def list_users(sm: async_sessionmaker[AsyncSession]) -> list[User]:
    """Every account, oldest first (the owner is the seed row)."""
    async with sm() as session:
        return list((await session.execute(select(User).order_by(User.created_at))).scalars().all())


async def set_real_covers_enabled(
    sm: async_sessionmaker[AsyncSession], user_id: uuid.UUID, enabled: bool
) -> User | None:
    """Set one member's private real-frame grant. Returns the updated user, or
    ``None`` when no such user exists (→ 404)."""
    async with sm() as session:
        user = await session.get(User, user_id)
        if user is None:
            return None
        user.real_covers_enabled = enabled
        await session.commit()
        await session.refresh(user)
        return user
