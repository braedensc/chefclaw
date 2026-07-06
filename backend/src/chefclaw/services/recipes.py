"""Recipe library service — list/get/patch/delete (plan §6).

The PATCH surface is exactly ``tags`` + ``user_notes``: the ``document`` JSONB
is NEVER user-editable (CLAUDE.md security model; the transport layer enforces
it again with an ``extra="forbid"`` body schema). DELETE is a HARD delete for
MVP — a job whose ``result_recipe_ids`` still references the row is history,
not a constraint.
"""

import uuid
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chefclaw.models import Recipe

__all__ = ["delete_recipe", "get_recipe", "list_recipes", "patch_recipe"]

_UNSET: Any = object()  # sentinel: distinguish "not provided" from explicit None

Sort = Literal["newest", "oldest"]


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
) -> Recipe | None:
    """Update the ONLY two user-editable fields. Absent fields are untouched
    (``user_notes=None`` explicitly clears the notes)."""
    recipe = await get_recipe(session, owner_id, recipe_id)
    if recipe is None:
        return None
    if tags is not _UNSET:
        recipe.tags = tags
    if user_notes is not _UNSET:
        recipe.user_notes = user_notes
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
