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

Derived estimates stay separate: :func:`validate_extraction` also SPLITS an
optional per-dish ``estimated`` object (spiciness/difficulty — the only
inferred numeric fields) OUT of each dish before document validation, so
``RecipeDocument`` never carries a derived value and the raw captures are never
overwritten (Hard Rule 7). Estimates land in their own column,
``source="derived"``, the same posture as the reserved nutrition_ref.

Auto-tags are the same shape: :func:`validate_extraction` SPLITS an optional
per-dish ``tags`` list OUT of each dish before document validation. Tags are
categorical ASSESSMENTS (cuisine / cooking method / key ingredient), the same
class of judgment as ``difficulty`` and ``cuisine_type`` — NOT verbatim food
data. They seed the user-editable ``recipes.tags`` column (never the immutable
``document``), so :func:`sanitize_tags` is deliberately LENIENT: bad tags are
dropped, never raised, because a nice-to-have default must not fail a whole
extraction.
"""

from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ValidationFailedError

__all__ = [
    "BilingualText",
    "EstimatedAttributes",
    "Ingredient",
    "Quantity",
    "RecipeDocument",
    "SourceInfo",
    "Step",
    "ValidatedDish",
    "sanitize_tags",
    "validate_document",
    "validate_estimated",
    "validate_extraction",
]

# Auto-tag cap and per-tag length ceiling (sanitize_tags). Kept small on
# purpose: 1–3 short labels are a smart default, not an index.
_MAX_TAGS = 3
_MAX_TAG_LENGTH = 24

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


class EstimatedAttributes(BaseModel):
    """DERIVED spiciness + difficulty estimates (Hard Rule 7).

    These are the ONLY inferred numeric fields in the pipeline — the model's
    ASSESSMENTS (0 = not spicy / very easy, 3 = very spicy / hard), null when
    it is genuinely unsure. They live in a SEPARATE column from the raw
    ``document`` and NEVER overwrite verbatim captures — ``source`` is fixed to
    ``"derived"`` so the flag can never masquerade as a stated value, the same
    posture as the reserved nutrition_ref.
    """

    model_config = _STRICT

    spiciness_level: int | None = Field(default=None, ge=0, le=3)
    difficulty_level: int | None = Field(default=None, ge=0, le=3)
    source: Literal["derived"] = "derived"


def validate_estimated(raw: dict | None) -> EstimatedAttributes | None:
    """Validate the optional per-dish ``estimated`` object.

    None or an empty dict ⇒ ``None`` (no estimate supplied). A non-empty dict
    is validated; on ANY failure a :class:`ValidationFailedError` is raised
    with ``raw_output`` carrying the offending object (never repaired).
    """
    if not raw:
        return None
    try:
        return EstimatedAttributes.model_validate(raw)
    except ValidationError as exc:
        raise ValidationFailedError(
            f"estimated attributes failed validation: {exc}", raw_output=raw
        ) from exc


def sanitize_tags(raw: object) -> list[str]:
    """Coerce the model's optional per-dish ``tags`` value into 1–3 clean labels.

    Tags are editable categorical METADATA (cuisine / cooking method / key
    ingredient — the same class of assessment as ``difficulty``), NOT verbatim
    captured food data, so this is deliberately LENIENT where document
    validation is strict: anything malformed is dropped, never raised — a
    nice-to-have default must never fail a whole extraction.

    Each tag is coerced to a stripped, lowercased, non-empty string of at most
    ``_MAX_TAG_LENGTH`` chars; non-strings, empties, and overlong tags are
    dropped; duplicates are removed preserving first-seen order; the result is
    capped at ``_MAX_TAGS``. Absent or non-list input ⇒ ``[]``.
    """
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = item.strip().lower()
        if not tag or len(tag) > _MAX_TAG_LENGTH:
            continue
        if tag in cleaned:
            continue
        cleaned.append(tag)
        if len(cleaned) == _MAX_TAGS:
            break
    return cleaned


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


class ValidatedDish(NamedTuple):
    """One validated dish: the verbatim ``document``, its DERIVED ``estimated``
    attributes (or None), and the sanitized auto-``tags`` (0–3, editable
    metadata). The estimates and tags are SPLIT OUT of the raw dish before
    document validation so ``RecipeDocument`` never carries a non-verbatim
    value (Hard Rule 7)."""

    document: RecipeDocument
    estimated: EstimatedAttributes | None
    tags: list[str]


def validate_extraction(
    raw_dishes: list[dict], source: SourceInfo
) -> list[ValidatedDish]:
    """Validate a full extraction (one video ⇒ N dishes) into
    :class:`ValidatedDish` triples of ``(document, estimated, tags)``.

    Each raw dish may carry an optional ``estimated`` object (derived spiciness
    + difficulty — Hard Rule 7) and an optional ``tags`` list (1–3 categorical
    labels — editable metadata, not verbatim capture). Both are SPLIT OUT of
    the dish BEFORE document validation so ``RecipeDocument`` stays
    ``extra="forbid"`` clean: the estimates land in their own column, the tags
    seed the user-editable ``recipes.tags`` column — never inside the verbatim
    ``document``. The document's ``source`` block is injected/overwritten from
    the pipeline's own knowledge — the model must not control provenance, so
    any model-emitted ``source`` is discarded. Inputs are never mutated.

    An empty ``raw_dishes`` is a validation failure: a stored extraction must
    contain at least one dish (mirrors the min-1 ingredients/steps rule).

    Raises :class:`~chefclaw.errors.ValidationFailedError` on ANY document or
    estimate failure, ``raw_output`` preserving the offending payload. Bad tags
    never raise — :func:`sanitize_tags` drops them (a smart default, not
    captured data).
    """
    if not raw_dishes:
        raise ValidationFailedError(
            "extraction produced no dishes — nothing to validate or store",
            raw_output=raw_dishes,
        )

    provenance = source.model_dump()
    results: list[ValidatedDish] = []
    for index, dish in enumerate(raw_dishes):
        if not isinstance(dish, dict):
            raise ValidationFailedError(
                f"dish {index} is not a JSON object (got {type(dish).__name__})",
                raw_output=dish,
            )
        # Split the derived estimates and auto-tags out (without mutating the
        # input) so the document validates clean under extra="forbid".
        estimated = validate_estimated(dish.get("estimated"))
        tags = sanitize_tags(dish.get("tags"))
        merged = {k: v for k, v in dish.items() if k not in ("estimated", "tags")}
        merged["source"] = provenance
        try:
            document = RecipeDocument.model_validate(merged)
        except ValidationError as exc:
            raise ValidationFailedError(
                f"dish {index} failed validation: {exc}", raw_output=merged
            ) from exc
        results.append(ValidatedDish(document, estimated, tags))
    return results
