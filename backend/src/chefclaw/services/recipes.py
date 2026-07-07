"""Recipe library service — list/get/patch/delete (plan §6).

The PATCH surface is ``tags`` + ``user_notes`` (free metadata) plus the two
derived ``estimated_*`` levels (owner corrections). The ``document`` JSONB is
NEVER user-editable (CLAUDE.md security model; the transport layer enforces it
again with an ``extra="forbid"`` body schema). DELETE is a HARD delete for
MVP — a job whose ``result_recipe_ids`` still references the row is history,
not a constraint.
"""

import uuid
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chefclaw.documents import EstimatedAttributes
from chefclaw.models import Recipe

__all__ = ["delete_recipe", "get_recipe", "list_recipes", "patch_recipe"]

_UNSET: Any = object()  # sentinel: distinguish "not provided" from explicit None

Sort = Literal["newest", "oldest"]


def _merge_user_estimate(
    current: dict[str, Any] | None,
    *,
    spiciness_level: int | None | Any,
    difficulty_level: int | None | Any,
) -> dict[str, Any]:
    """Overlay owner corrections onto the ``estimated`` column, re-flagged
    ``source="user"``.

    Merge posture (the classification the design-system ADR left open): the
    ``estimated`` object carries ONE ``source`` for both levels, so ANY owner
    edit makes the whole object owner-authored — a coarse but honest signal that
    a future re-derivation (deferred re-extraction ADR) must NOT overwrite it.
    Only the level(s) actually sent are changed; an unsent level keeps its
    current value (or ``None`` when the column was null). The object is rebuilt
    even when both levels end up ``None`` — clearing an estimate is itself an
    owner decision the ``"user"`` flag must preserve against re-derivation.
    Building it through :class:`EstimatedAttributes` re-validates the 0–3 range
    and guarantees the stored shape matches the schema exactly."""
    current = current if isinstance(current, dict) else {}
    spiciness = (
        current.get("spiciness_level") if spiciness_level is _UNSET else spiciness_level
    )
    difficulty = (
        current.get("difficulty_level") if difficulty_level is _UNSET else difficulty_level
    )
    return EstimatedAttributes(
        spiciness_level=spiciness,
        difficulty_level=difficulty,
        source="user",
    ).model_dump(mode="json")


async def list_recipes(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    q: str | None = None,
    platform: str | None = None,
    tag: str | None = None,
    sort: Sort = "newest",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Recipe], int]:
    """Owner-scoped library page: ``(items, total)``."""
    stmt = select(Recipe).where(Recipe.owner_id == owner_id)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(Recipe.title_en.ilike(pattern), Recipe.title_original.ilike(pattern))
        )
    if platform:
        stmt = stmt.where(Recipe.platform == platform)
    if tag:
        stmt = stmt.where(Recipe.tags.any(tag))  # tag = ANY(tags)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))

    order = Recipe.created_at.desc() if sort == "newest" else Recipe.created_at.asc()
    stmt = stmt.order_by(order, Recipe.id.desc()).limit(limit).offset(offset)
    items = list((await session.execute(stmt)).scalars().all())
    return items, int(total or 0)


async def get_recipe(
    session: AsyncSession, owner_id: uuid.UUID, recipe_id: uuid.UUID
) -> Recipe | None:
    stmt = select(Recipe).where(Recipe.id == recipe_id, Recipe.owner_id == owner_id)
    return (await session.execute(stmt)).scalars().first()


async def patch_recipe(
    session: AsyncSession,
    owner_id: uuid.UUID,
    recipe_id: uuid.UUID,
    *,
    tags: list[str] | Any = _UNSET,
    user_notes: str | None | Any = _UNSET,
    estimated_spiciness_level: int | None | Any = _UNSET,
    estimated_difficulty_level: int | None | Any = _UNSET,
) -> Recipe | None:
    """Update the user-editable fields. Absent fields are untouched
    (``user_notes=None`` explicitly clears the notes). A provided
    ``estimated_*`` level rebuilds the ``estimated`` column as an owner
    correction (``source="user"``) — see :func:`_merge_user_estimate`."""
    recipe = await get_recipe(session, owner_id, recipe_id)
    if recipe is None:
        return None
    if tags is not _UNSET:
        recipe.tags = tags
    if user_notes is not _UNSET:
        recipe.user_notes = user_notes
    if estimated_spiciness_level is not _UNSET or estimated_difficulty_level is not _UNSET:
        recipe.estimated = _merge_user_estimate(
            recipe.estimated,
            spiciness_level=estimated_spiciness_level,
            difficulty_level=estimated_difficulty_level,
        )
    await session.commit()
    return recipe


async def delete_recipe(
    session: AsyncSession, owner_id: uuid.UUID, recipe_id: uuid.UUID
) -> bool:
    """HARD delete (MVP decision). Returns False when not found."""
    recipe = await get_recipe(session, owner_id, recipe_id)
    if recipe is None:
        return False
    await session.delete(recipe)
    await session.commit()
    return True
