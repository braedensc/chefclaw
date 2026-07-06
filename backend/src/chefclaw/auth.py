"""Bearer-token auth behind ONE swappable FastAPI dependency.

Routers depend only on ``require_owner``. Today it validates the single
``CHEFCLAW_API_TOKEN`` and resolves the seeded owner row; a real identity
system (sessions/passkeys/OAuth) replaces this one dependency at multi-user
without touching the service layer.

Disabled-closed: an empty configured token means every request is rejected
with an actionable 401 — there is no unauthenticated mode.
"""

import hmac
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from chefclaw.config import Settings, get_settings
from chefclaw.db import get_sessionmaker
from chefclaw.models import User

_bearer_scheme = HTTPBearer(auto_error=False)

# Per-process cache of the seeded owner id (single-user today; the cache is
# reset only by process restart, which is when the seed could ever change).
_cached_owner_id: uuid.UUID | None = None


async def fetch_owner_id() -> uuid.UUID | None:
    """Look up the seeded owner row (users LIMIT 1). Stubbed in tests."""
    async with get_sessionmaker()() as session:
        result = await session.execute(select(User.id).order_by(User.created_at).limit(1))
        return result.scalars().first()


async def require_owner(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> uuid.UUID:
    """Validate the bearer token and return the owner's user id."""
    global _cached_owner_id

    configured = settings.chefclaw_api_token
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Authentication is not configured, so all requests are refused: "
                "set CHEFCLAW_API_TOKEN in the server environment and restart."
            ),
        )

    provided = credentials.credentials if credentials is not None else ""
    if not provided or not hmac.compare_digest(provided.encode(), configured.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if _cached_owner_id is None:
        try:
            owner_id = await fetch_owner_id()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unreachable while resolving the owner account.",
            ) from exc
        if owner_id is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "No owner row found — run migrations "
                    "(uv run alembic upgrade head) to seed the owner."
                ),
            )
        _cached_owner_id = owner_id

    return _cached_owner_id
