"""The recipe library endpoints (plan §6): list / detail / patch / delete.

PATCH accepts tags + user_notes + the two derived estimate levels
(RecipePatch is extra='forbid' — a body mentioning `document` or anything else
is a 422). DELETE is a hard delete.
"""

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from chefclaw import db
from chefclaw.auth import require_owner
from chefclaw.config import Settings, get_settings
from chefclaw.routers.deps import error_response, get_job_store
from chefclaw.schemas import ErrorBody, JobOut, RecipeDetail, RecipePage, RecipePatch, RecipeSummary
from chefclaw.services import jobs as jobs_service
from chefclaw.services import recipes as recipes_service
from chefclaw.services.recipes import Sort
from chefclaw.services.repo import JobStore

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


@router.get(
    "/{recipe_id}/image",
    response_model=None,  # a file stream, not a schema-modeled body
    response_class=FileResponse,
    responses={
        200: {
            "content": {"image/jpeg": {}},
            "description": "The recipe's generated illustration.",
        },
        **_NOT_FOUND,
    },
)
async def get_recipe_image(
    recipe_id: uuid.UUID,
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    session: Annotated[AsyncSession, Depends(db.get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse | JSONResponse:
    """Stream the generated illustration. One 404 covers every miss — no
    recipe, no illustration generated yet, file gone from the archive."""
    recipe = await recipes_service.get_recipe(session, owner_id, recipe_id)
    if recipe is None or recipe.image_url is None:
        return error_response(404, "not_found", f"no image for recipe {recipe_id}")
    image_path = Path(recipe.image_url).resolve()
    media_root = Path(settings.media_dir).resolve()
    # Belt-and-braces: only ever serve files from inside the media archive.
    if not image_path.is_relative_to(media_root) or not image_path.is_file():
        return error_response(404, "not_found", f"no image for recipe {recipe_id}")
    return FileResponse(
        image_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post(
    "/{recipe_id}/illustration",
    status_code=202,
    response_model=JobOut,
    responses={
        200: {"model": JobOut, "description": "Existing active illustration job (dedupe hit)"},
        **_NOT_FOUND,
    },
)
async def regenerate_illustration(
    recipe_id: uuid.UUID,
    response: Response,
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    session: Annotated[AsyncSession, Depends(db.get_session)],
    store: Annotated[JobStore, Depends(get_job_store)],
) -> JobOut | JSONResponse:
    """Enqueue an illustration job to (re)generate this recipe's cover — the
    detail-page 'Regenerate illustration' affordance and the jobs-drawer Retry
    for a failed illustration job both land here. Owner-scoped: a recipe that
    isn't the caller's is a 404 (never enqueue paid work for another owner).
    202 when a fresh job was enqueued, 200 when an active illustration job for
    this recipe already exists (dedupe)."""
    recipe = await recipes_service.get_recipe(session, owner_id, recipe_id)
    if recipe is None:
        return error_response(404, "not_found", f"no recipe {recipe_id}")
    job, existing = await jobs_service.enqueue_illustration(store, owner_id, recipe_id)
    response.status_code = 200 if existing else 202
    return JobOut.model_validate(job)


@router.patch("/{recipe_id}", response_model=RecipeDetail, responses=_NOT_FOUND)
async def patch_recipe(
    recipe_id: uuid.UUID,
    body: RecipePatch,
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    session: Annotated[AsyncSession, Depends(db.get_session)],
) -> RecipeDetail | JSONResponse:
    # Only forward fields the client actually sent — an absent field is
    # untouched, an explicit null clears (user_notes and the estimate levels).
    provided = body.model_fields_set
    kwargs: dict[str, object] = {}
    if "tags" in provided:
        kwargs["tags"] = body.tags if body.tags is not None else []
    if "user_notes" in provided:
        kwargs["user_notes"] = body.user_notes
    if "estimated_spiciness_level" in provided:
        kwargs["estimated_spiciness_level"] = body.estimated_spiciness_level
    if "estimated_difficulty_level" in provided:
        kwargs["estimated_difficulty_level"] = body.estimated_difficulty_level
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
