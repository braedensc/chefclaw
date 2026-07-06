"""API transport schemas (Pydantic) — the OpenAPI contract the typed TS
client is generated from.

``JobOut`` is THE extract response (plan §16.2): ``POST /api/recipes/extract``
and ``/upload`` always return the job resource — 202 new, 200 existing —
never a recipe body; ``result_recipe_ids`` carries the recipes.

``RecipePatch`` is ``extra="forbid"`` on purpose: the ``document`` is never
user-editable, so a PATCH mentioning it (or any other field) is a 422, not a
silent ignore.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ErrorBody",
    "ExtractRequest",
    "JobOut",
    "RecipeDetail",
    "RecipePage",
    "RecipePatch",
    "RecipeSummary",
]


class ErrorBody(BaseModel):
    """Typed error payload: ``error_type`` is the stable taxonomy string the
    UI maps onto actions (runbook link, retry button, hard stop)."""

    error_type: str
    detail: str


class ExtractRequest(BaseModel):
    url: str = Field(min_length=1)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    status: str
    platform: str | None
    canonical_id: str | None
    attempts: int
    error_type: str | None
    error_detail: str | None
    result_recipe_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class RecipeSummary(BaseModel):
    """Library-card shape (list endpoint)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title_en: str | None
    title_original: str | None
    platform: str
    canonical_id: str
    dish_index: int
    status: str
    tags: list[str]
    created_at: datetime


class RecipeDetail(RecipeSummary):
    """Full recipe including the (read-only) document."""

    source_url: str
    user_notes: str | None
    document: dict[str, Any]
    extraction_meta: dict[str, Any]


class RecipePage(BaseModel):
    items: list[RecipeSummary]
    total: int
    limit: int
    offset: int


class RecipePatch(BaseModel):
    """The ONLY user-editable fields. extra='forbid' rejects document edits."""

    model_config = ConfigDict(extra="forbid")

    tags: list[str] | None = None
    user_notes: str | None = None
