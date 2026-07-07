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
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "ErrorBody",
    "ExtractRequest",
    "InviteCreate",
    "InviteList",
    "InviteOut",
    "InvitePublicOut",
    "JobOut",
    "RecipeDetail",
    "MeOut",
    "RecipePage",
    "RecipePatch",
    "RecipeSummary",
    "SpendDay",
    "SpendModelSlice",
    "SpendSummaryOut",
]


class MeOut(BaseModel):
    """GET /api/me — the authenticated identity. ``id`` is the owner_id the
    service scopes on; ``is_admin`` gates admin-UI visibility only (server-
    derived, never a writable field — critique M9)."""

    id: uuid.UUID
    name: str
    email: str
    is_admin: bool


class InviteCreate(BaseModel):
    """POST /api/admin/invites body. Lightweight email shape check (a friends-
    invite flow, not a validation fortress) — normalization happens server-side."""

    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _looks_like_email(cls, v: str) -> str:
        s = v.strip()
        if "@" not in s or " " in s or "." not in s.rsplit("@", 1)[-1]:
            raise ValueError("not a valid email address")
        return s


class InviteOut(BaseModel):
    """An invite as the admin sees it — NEVER the token_hash. ``dev_activation_
    link`` is present ONLY when chefclaw_email='fake' (the real link is emailed)."""

    id: uuid.UUID
    email: str
    status: str
    expires_at: datetime
    created_at: datetime
    accepted_at: datetime | None = None
    dev_activation_link: str | None = None


class InviteList(BaseModel):
    items: list[InviteOut]


class InvitePublicOut(BaseModel):
    """GET /api/invites/{token} — the public invite-accept shape (M13). ``status``
    is 'pending' | 'invalid'; ``email`` is revealed ONLY for a live pending
    invite (a missing/expired/revoked token is a uniform 'invalid', no email)."""

    status: str
    email: str | None = None


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
    # The user's originally pasted URL (payload provenance). The UI's retry
    # affordance re-POSTs it: a failed job is never ACTIVE for dedupe, so the
    # re-POST creates a fresh job (jobs ADR).
    url: str | None = None
    # For an ILLUSTRATION job: the recipe(s) it (re)generates covers for
    # (lifted from the payload). Empty for extract/upload jobs. The drawer's
    # Retry re-enqueues an illustration job for these recipes.
    recipe_ids: list[uuid.UUID] = []
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _lift_url_from_payload(cls, data: Any) -> Any:
        """ORM ``Job`` → dict of the contract fields, with ``url`` lifted out
        of the internal ``payload`` JSON (the payload itself never leaves the
        API). Dicts pass through untouched."""
        if isinstance(data, dict) or not hasattr(data, "payload"):
            return data
        payload = data.payload or {}
        return {
            "id": data.id,
            "type": data.type,
            "status": data.status,
            "platform": data.platform,
            "canonical_id": data.canonical_id,
            "attempts": data.attempts,
            "error_type": data.error_type,
            "error_detail": data.error_detail,
            "result_recipe_ids": data.result_recipe_ids,
            "url": payload.get("url"),
            "recipe_ids": payload.get("recipe_ids", []),
            "created_at": data.created_at,
            "updated_at": data.updated_at,
        }


# The RecipeSummary fields _project_from_document computes rather than copies.
_PROJECTED_FIELDS = frozenset(
    {
        "has_image",
        "difficulty",
        "total_time_minutes",
        "ingredient_count",
        "estimated_spiciness_level",
        "estimated_difficulty_level",
        "estimated_source",
    }
)


class RecipeSummary(BaseModel):
    """Library-card shape (list endpoint). ``difficulty`` /
    ``total_time_minutes`` are lifted VERBATIM from the stored validated
    document; ``ingredient_count`` is the length of its ingredients list — a
    structural count, not a food quantity (Hard Rule 7 governs food data like
    amounts/weights, which stay verbatim inside the document). ``has_image``
    derives from the server-side ``image_url`` (the generated illustration
    path), which itself never leaves the API (the /image endpoint streams the
    file). ``estimated_spiciness_level`` / ``estimated_difficulty_level`` are
    the 0–3 estimates projected from the separate ``estimated`` column (never
    inside the verbatim document); ``estimated_source`` says whether they are the
    model's ``"derived"`` guess (flag 'estimated' in the UI) or an owner
    ``"user"`` correction."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title_en: str | None
    title_original: str | None
    platform: str
    canonical_id: str
    dish_index: int
    status: str
    tags: list[str]
    has_image: bool = False
    difficulty: str | None = None
    total_time_minutes: int | None = None
    ingredient_count: int | None = None
    # Estimates (0–3), None when the extraction supplied none / the column is
    # null. Projected from the `estimated` column. `estimated_source` records
    # provenance: "derived" = the model's assessment (flag it "estimated" in the
    # UI), "user" = an owner correction (PATCH-able — drop the flag), None when
    # there is no estimate at all.
    estimated_spiciness_level: int | None = None
    estimated_difficulty_level: int | None = None
    estimated_source: Literal["derived", "user"] | None = None
    created_at: datetime

    @staticmethod
    def _document_projections(document: Any) -> dict[str, Any]:
        document = document if isinstance(document, dict) else {}
        ingredients = document.get("ingredients")
        return {
            "difficulty": document.get("difficulty"),
            "total_time_minutes": document.get("total_time_minutes"),
            "ingredient_count": len(ingredients) if isinstance(ingredients, list) else None,
        }

    @staticmethod
    def _estimated_projections(estimated: Any) -> dict[str, Any]:
        # None-safe: a null `estimated` column → both levels None.
        estimated = estimated if isinstance(estimated, dict) else {}
        return {
            "estimated_spiciness_level": estimated.get("spiciness_level"),
            "estimated_difficulty_level": estimated.get("difficulty_level"),
            "estimated_source": estimated.get("source"),
        }

    @model_validator(mode="before")
    @classmethod
    def _project_from_document(cls, data: Any) -> Any:
        """ORM ``Recipe`` → the contract fields (copied generically from
        ``cls.model_fields``, so RecipeDetail's extras ride along without a
        hand-kept list) plus the computed projections. Dicts pass through —
        re-projected only when they carry a ``document`` key. The
        response-revalidation dict path (RecipeDetail.model_dump) has no
        ``image_url``/``estimated`` keys, so those projections are only
        (re)computed when their source key is present — never clobbered."""
        if isinstance(data, dict):
            if "document" not in data:
                return data
            projected = {**data, **cls._document_projections(data["document"])}
            if "image_url" in data:
                projected["has_image"] = data["image_url"] is not None
            if "estimated" in data:
                projected.update(cls._estimated_projections(data["estimated"]))
            return projected
        if not hasattr(data, "document"):
            return data
        projected = {
            name: getattr(data, name)
            for name in cls.model_fields
            if name not in _PROJECTED_FIELDS and hasattr(data, name)
        }
        projected.update(cls._document_projections(data.document))
        projected["has_image"] = data.image_url is not None
        projected.update(cls._estimated_projections(data.estimated))
        return projected


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
    """The user-editable fields. extra='forbid' rejects document edits.

    ``tags`` / ``user_notes`` are free metadata; the two ``estimated_*`` fields
    let the owner CORRECT the derived 0–3 estimates (a provided value re-flags
    the ``estimated`` column ``source="user"``, taking precedence over the
    model's derivation — see ``services.recipes.patch_recipe``). All are
    optional; only fields actually present in the body are applied
    (``model_fields_set``), so an explicit ``null`` clears while an absent field
    is untouched. ``strict=True`` on the estimate ints blocks bool→int coercion
    (``True`` is not ``spiciness_level=1``) — the same guard the document schema
    keeps."""

    model_config = ConfigDict(extra="forbid")

    tags: list[str] | None = None
    user_notes: str | None = None
    estimated_spiciness_level: int | None = Field(default=None, ge=0, le=3, strict=True)
    estimated_difficulty_level: int | None = Field(default=None, ge=0, le=3, strict=True)


class SpendModelSlice(BaseModel):
    """One model's share of a day's ledger (GET /api/spend, V2-A ADR)."""

    model: str
    cost_usd: float
    attempts: int
    tokens_in: int
    tokens_out: int
    tokens_thinking: int


class SpendDay(BaseModel):
    """One UTC day of ledger activity; days with zero attempts are omitted."""

    date: date
    cost_usd: float
    attempts: int
    models: list[SpendModelSlice]


class SpendSummaryOut(BaseModel):
    """The spend readout: per-day/per-model history over the requested window
    plus month-to-date and the configured caps. ``budget_monthly_usd`` /
    ``daily_attempt_cap`` are null when the budget config is fail-closed —
    the UI must say 'extraction disabled', never invent a cap."""

    period_days: int
    total_usd: float
    month_to_date_usd: float
    attempts_today: int
    budget_monthly_usd: float | None = None
    daily_attempt_cap: int | None = None
    days: list[SpendDay]
