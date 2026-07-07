"""FakeExtractor — the config-selectable safe default (plan §16.9).

Zero network, zero spend, deterministic. The golden paste-to-card suite and the
worker tests drive their scenarios through this adapter: canned dishes, warning
injection, and failure injection (raise any error from the typed taxonomy).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from chefclaw.extractors import ExtractionOutcome, ExtractionUsage

FAKE_PROMPT_VERSION = "v4"
FAKE_MODEL_ID = "fake-extractor"

# One realistic bilingual dish matching the §5 document shape MINUS the source
# block (the pipeline injects provenance). Faithful-capture rules hold even in
# fixtures: the 盐 ("salt") ingredient is "适量" — value null, unit null,
# unit_type "approx"; grams only where explicitly stated.
_DEFAULT_DISH: dict = {
    "dish_name": {"en": "Red-braised pork belly", "original": "红烧肉"},
    "cuisine_type": "Chinese (Jiangnan)",
    "difficulty": "medium",
    "total_time_minutes": 75,
    "servings": None,
    "ingredients": [
        {
            "raw_text": "五花肉500克",
            "name": {"en": "pork belly", "original": "五花肉"},
            "quantity": {"raw_text": "500克", "value": 500, "unit": "g", "unit_type": "mass"},
            "quantity_grams_stated": 500,
            "prep_state": "raw",
            "notes": None,
            "nutrition_ref": None,
        },
        {
            "raw_text": "冰糖两大勺",
            "name": {"en": "rock sugar", "original": "冰糖"},
            "quantity": {"raw_text": "两大勺", "value": 2, "unit": "tbsp", "unit_type": "volume"},
            "quantity_grams_stated": None,
            "prep_state": None,
            "notes": None,
            "nutrition_ref": None,
        },
        {
            "raw_text": "盐适量",
            "name": {"en": "salt", "original": "盐"},
            "quantity": {"raw_text": "适量", "value": None, "unit": None, "unit_type": "approx"},
            "quantity_grams_stated": None,
            "prep_state": None,
            "notes": None,
            "nutrition_ref": None,
        },
    ],
    "equipment": ["炒锅 (wok)"],
    "steps": [
        {
            "step_number": 1,
            "instruction": "Blanch the pork belly cubes in cold water brought to a boil, "
            "then drain. 五花肉切块，冷水下锅焯水。",
            "duration": None,
            "visual_cues": "Skim until the surface foam is gone.",
            "technique_notes": "Start from cold water so the blood draws out.",
        },
        {
            "step_number": 2,
            "instruction": "Melt the rock sugar in oil over low heat, then toss the pork "
            "to coat. 小火炒糖色，下肉翻炒上色。",
            "duration": None,
            "visual_cues": "Sugar turns amber and bubbles before the pork goes in.",
            "technique_notes": "Low heat — burnt caramel turns bitter.",
        },
        {
            "step_number": 3,
            "instruction": "Add water to cover, simmer covered, then reduce. Season with "
            "salt to taste. 加水没过，小火炖煮收汁，盐适量调味。",
            "duration": "1小时 (1 hour)",
            "visual_cues": "Sauce reduced to a glossy coat on the meat.",
            "technique_notes": None,
        },
    ],
    "tips": ["Skim early; a clean braise keeps the sauce clear."],
    # Derived estimates (v2): split out by validate_extraction into the
    # separate `estimated` column, never into the verbatim document.
    "estimated": {"spiciness_level": 1, "difficulty_level": 1},
    # Auto-tags (v3): split out into the user-editable `tags` column as a smart
    # default — categorical assessments, not verbatim capture.
    "tags": ["braise", "pork", "classic"],
    # Cover-sprite pick (v4): the model's choice from the catalog menu, split out
    # by validate_extraction and resolved against the catalog. A real, known id —
    # the deterministic matcher would independently pick the same one, so the
    # fixture exercises the trusted-model-id path deterministically.
    "cover_sprite_id": "red-braised-pork",
}

_DEFAULT_USAGE = ExtractionUsage(
    model_id=FAKE_MODEL_ID,
    prompt_version=FAKE_PROMPT_VERSION,
    tokens_in=1000,
    tokens_out=250,
    tokens_thinking=0,
)


@dataclass
class FakeCall:
    """One recorded extract() invocation — worker tests assert against these."""

    video_path: Path
    source_title: str | None
    source_duration_seconds: int | None


class FakeExtractor:
    """ExtractorAdapter double with injection ergonomics.

    - ``dishes`` — canned output (default: one realistic bilingual dish).
    - ``warnings`` — surfaced verbatim in the outcome.
    - ``failure`` — raised as-is on every extract() call (pass any taxonomy
      error, e.g. ``RateLimitedError("...")``, to drive unhappy paths).
    - ``usage`` — deterministic token numbers for ledger tests.
    - ``calls`` — every invocation recorded for assertion.
    """

    def __init__(
        self,
        dishes: list[dict] | None = None,
        warnings: list[str] | None = None,
        failure: Exception | None = None,
        usage: ExtractionUsage | None = None,
    ) -> None:
        self._dishes = dishes if dishes is not None else [_DEFAULT_DISH]
        self._warnings = warnings if warnings is not None else []
        self._failure = failure
        self._usage = usage if usage is not None else _DEFAULT_USAGE
        self.calls: list[FakeCall] = []

    async def extract(
        self,
        video_path: Path,
        source_title: str | None,
        source_duration_seconds: int | None,
    ) -> ExtractionOutcome:
        self.calls.append(FakeCall(video_path, source_title, source_duration_seconds))
        if self._failure is not None:
            raise self._failure
        return ExtractionOutcome(
            dishes=deepcopy(self._dishes),  # callers must never mutate the fixture
            usage=deepcopy(self._usage),
            warnings=list(self._warnings),
        )


def default_dish() -> dict:
    """A fresh copy of the default fixture dish (for tests that assert shape)."""
    return deepcopy(_DEFAULT_DISH)
