"""The recipe ``document`` schema — plan §5, the load-bearing contract.

Every stored recipe passes through :func:`validate_document`; nothing reaches
the database that this module has not accepted verbatim.

**Hard Rule 7 (never fabricate food data)** governs this module: quantities are
captured verbatim from the source — "两大勺" stays "两大勺"; "适量"/"to taste"
becomes ``value=None, unit=None, unit_type="approx"``; ``quantity_grams_stated``
is populated ONLY when the host explicitly states a weight. **Validation checks
consistency but NEVER fills, coerces, or estimates** — a document that fails
validation is rejected whole (raw output preserved on the error for debugging),
never repaired.

Coercion contract (all models are pydantic strict mode, ``extra="forbid"``):

- Strings NEVER become numbers: ``"2"`` for a float/int field is a validation
  failure, not ``2.0`` — a silent parse is one step from a silent fabrication.
- Bools NEVER become ints (``True`` is not ``servings=1``).
- The ONE accepted numeric coercion is lossless int → float (JSON ``2`` for a
  float field validates as ``2.0`` — the same number; JSON does not distinguish
  the two types).
- Unknown keys are rejected everywhere (``extra="forbid"``).
- Impossible values are REJECTED, never adjusted: non-positive quantities/
  weights/servings/minutes and empty-string name sides fail validation whole —
  a consistency check that repairs is a fabrication with extra steps.
- ``nutrition_ref`` is reserved for pillar 2 (nutrition) and MUST be ``None``
  at extraction time — the schema rejects any non-null value so the extractor
  can never smuggle one in.

Provenance is pipeline-owned: :func:`validate_extraction` overwrites each
dish's ``source`` block from the pipeline's own knowledge — the model never
controls where a recipe claims to come from.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ValidationFailedError

__all__ = [
    "BilingualText",
    "Ingredient",
    "Quantity",
    "RecipeDocument",
    "SourceInfo",
    "Step",
    "validate_document",
    "validate_extraction",
]

# Strict everywhere: no type coercion beyond lossless int -> float, and no
# unknown keys — see the module docstring's coercion contract.
_STRICT = ConfigDict(extra="forbid", strict=True)


class BilingualText(BaseModel):
    """A translated field that keeps its original (plan §2.5 — original
    language is data). At least one side must be present, and a present side
    must be non-empty — ``{"en": ""}`` is an absent name wearing a string."""

    model_config = _STRICT

    en: str | None = Field(default=None, min_length=1)
    original: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _at_least_one_side(self) -> "BilingualText":
        if self.en is None and self.original is None:
            raise ValueError("BilingualText requires at least one of 'en' or 'original'")
        return self


class Quantity(BaseModel):
    """A verbatim-captured quantity. ``raw_text`` is the source truth;
    ``value``/``unit`` exist only when the source actually stated them
    ("适量" ⇒ value=None, unit=None, unit_type="approx")."""

    model_config = _STRICT

    raw_text: str = Field(min_length=1)
    value: float | None = Field(default=None, gt=0)  # a stated amount is positive
    unit: str | None = None
    unit_type: Literal["volume", "mass", "count", "approx"] | None = None


class Ingredient(BaseModel):
    model_config = _STRICT

    raw_text: str = Field(min_length=1, description="Verbatim from the source — immutable.")
    name: BilingualText
    quantity: Quantity | None = None

    @model_validator(mode="before")
    @classmethod
    def _all_null_quantity_is_null(cls, data: object) -> object:
        """Canonicalize the two encodings of "no quantity stated".

        Models frequently emit ``quantity: {raw_text: null, value: null, unit:
        null, unit_type: null}`` — or the same with ``unit_type: "approx"`` as
        a classification of the absence — where the contract wants
        ``quantity: null``. With no captured text, no value, and no unit, the
        object encodes exactly the same absence, so collapsing it to ``None``
        creates and destroys no food data — a canonicalization, NOT a repair
        (Hard Rule 7 intact). An object carrying an actual ``value`` or
        ``unit`` without ``raw_text`` is a number from nowhere — genuinely
        inconsistent data, still rejected.
        """
        if isinstance(data, dict):
            q = data.get("quantity")
            if (
                isinstance(q, dict)
                and q
                and q.get("raw_text") is None
                and q.get("value") is None
                and q.get("unit") is None
                and set(q) <= {"raw_text", "value", "unit", "unit_type"}
            ):
                data = {**data, "quantity": None}
        return data
    quantity_grams_stated: float | None = Field(
        default=None,
        gt=0,
        description="ONLY if the host explicitly states a weight — never estimated.",
    )
    # Enum grows EVIDENCE-DRIVEN: values are added when real videos surface
    # them (validation_failed preserves the raw output, so a miss is loud).
    # "frozen" added 2026-07-06 from the first real Rednote acceptance video.
    prep_state: Literal["dried", "fresh", "cooked", "raw", "frozen"] | None = None
    notes: str | None = None
    # Reserved for pillar 2 (nutrition). The `None` type IS the validator:
    # any non-null value is rejected — the extractor never fills this.
    nutrition_ref: None = None


class Step(BaseModel):
    model_config = _STRICT

    step_number: int = Field(ge=1)
    instruction: str = Field(min_length=1)
    duration: str | None = None
    visual_cues: str | None = None
    technique_notes: str | None = None


class SourceInfo(BaseModel):
    """Provenance — injected by the pipeline (validate_extraction), never
    trusted from model output. 'local' is the Tier-2 file-upload floor
    (plan §16.10)."""

    model_config = _STRICT

    platform: Literal["bilibili", "rednote", "local"]
    url: str = Field(min_length=1)
    creator: str | None = None
    video_duration_seconds: int | None = Field(default=None, ge=0)


class RecipeDocument(BaseModel):
    """The JSONB ``recipes.document`` payload (plan §5). Never user-editable
    once stored; only tags/user_notes are (and those live outside this doc)."""

    model_config = _STRICT

    dish_name: BilingualText
    cuisine_type: str | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    total_time_minutes: int | None = Field(default=None, ge=1)
    servings: int | None = Field(default=None, ge=1)  # often unstated ⇒ None — NEVER guessed
    ingredients: list[Ingredient] = Field(min_length=1)
    equipment: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(min_length=1)
    tips: list[str] = Field(default_factory=list)
    source: SourceInfo

    @model_validator(mode="after")
    def _steps_strictly_ascending(self) -> "RecipeDocument":
        numbers = [step.step_number for step in self.steps]
        for previous, current in zip(numbers, numbers[1:], strict=False):
            if current <= previous:
                raise ValueError(f"step_numbers must be strictly ascending, got {numbers}")
        return self


def validate_document(raw: dict) -> RecipeDocument:
    """Validate one raw dish dict against the document schema.

    Raises :class:`~chefclaw.errors.ValidationFailedError` on ANY failure,
    with ``raw_output`` carrying the exact input object for debugging —
    never repaired, never silently 'fixed' (Hard Rule 7).
    """
    try:
        return RecipeDocument.model_validate(raw)
    except ValidationError as exc:
        raise ValidationFailedError(
            f"recipe document failed validation: {exc}", raw_output=raw
        ) from exc


def validate_extraction(raw_dishes: list[dict], source: SourceInfo) -> list[RecipeDocument]:
    """Validate a full extraction (one video ⇒ N dishes) into documents.

    The ``source`` block of every dish is injected/overwritten from the
    pipeline's own knowledge — the model must not control provenance, so any
    model-emitted ``source`` is discarded. Inputs are never mutated.

    An empty ``raw_dishes`` is a validation failure: a stored extraction must
    contain at least one dish (mirrors the min-1 ingredients/steps rule).

    Raises :class:`~chefclaw.errors.ValidationFailedError` on ANY failure,
    ``raw_output`` preserving the offending payload.
    """
    if not raw_dishes:
        raise ValidationFailedError(
            "extraction produced no dishes — nothing to validate or store",
            raw_output=raw_dishes,
        )

    provenance = source.model_dump()
    documents: list[RecipeDocument] = []
    for index, dish in enumerate(raw_dishes):
        if not isinstance(dish, dict):
            raise ValidationFailedError(
                f"dish {index} is not a JSON object (got {type(dish).__name__})",
                raw_output=dish,
            )
        merged = {**dish, "source": provenance}
        try:
            documents.append(RecipeDocument.model_validate(merged))
        except ValidationError as exc:
            raise ValidationFailedError(
                f"dish {index} failed validation: {exc}", raw_output=merged
            ) from exc
    return documents
