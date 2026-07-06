"""The recipe library endpoints (plan §6): list / detail / patch / delete.

PATCH accepts ONLY tags + user_notes (RecipePatch is extra='forbid' — a body
mentioning `document` or anything else is a 422). DELETE is a hard delete.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from chefclaw import db
from chefclaw.auth import require_owner
from chefclaw.routers.deps import error_response
from chefclaw.schemas import ErrorBody, RecipeDetail, RecipePage, RecipePatch, RecipeSummary
from chefclaw.services import recipes as recipes_service
from chefclaw.services.recipes import Sort

router = APIRouter(prefix="/api/recipes", tags=["recipes"])

_NOT_FOUND = {404: {"model": ErrorBody}}


@router.get("", response_model=RecipePage)
async def list_recipes(
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    session: Annotated[AsyncSession, Depends(db.get_session)],
    q: str | None = None,
    platform: str | None = None,
    tag: str | None = None,
    sort: Sort = "newest",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RecipePage:
    items, total = await recipes_service.list_recipes(
        session,
        owner_id,
        q=q,
        platform=platform,
        tag=tag,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return RecipePage(
        items=[RecipeSummary.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{recipe_id}", response_model=RecipeDetail, responses=_NOT_FOUND)
async def get_recipe(
    recipe_id: uuid.UUID,
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    session: Annotated[AsyncSession, Depends(db.get_session)],
) -> RecipeDetail | JSONResponse:
    recipe = await recipes_service.get_recipe(session, owner_id, recipe_id)
    if recipe is None:
        return error_response(404, "not_found", f"no recipe {recipe_id}")
    return RecipeDetail.model_validate(recipe)


@router.patch("/{recipe_id}", response_model=RecipeDetail, responses=_NOT_FOUND)
async def patch_recipe(
    recipe_id: uuid.UUID,
    body: RecipePatch,
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    session: Annotated[AsyncSession, Depends(db.get_session)],
) -> RecipeDetail | JSONResponse:
    # Only forward fields the client actually sent — an absent field is
    # untouched, an explicit null clears (user_notes only).
    provided = body.model_fields_set
    kwargs = {}
    if "tags" in provided:
        kwargs["tags"] = body.tags if body.tags is not None else []
    if "user_notes" in provided:
        kwargs["user_notes"] = body.user_notes
    recipe = await recipes_service.patch_recipe(session, owner_id, recipe_id, **kwargs)
    if recipe is None:
        return error_response(404, "not_found", f"no recipe {recipe_id}")
    return RecipeDetail.model_validate(recipe)


@router.delete("/{recipe_id}", status_code=204, responses=_NOT_FOUND)
async def delete_recipe(
    recipe_id: uuid.UUID,
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    session: Annotated[AsyncSession, Depends(db.get_session)],
) -> Response:
    deleted = await recipes_service.delete_recipe(session, owner_id, recipe_id)
    if not deleted:
        return error_response(404, "not_found", f"no recipe {recipe_id}")
    return Response(status_code=204)
