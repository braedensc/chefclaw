"""ImageGeneratorAdapter — the illustration-generation seam (V2-E, 2026-07-06).

The card cover is a GENERATED cartoon illustration of the dish, NOT a real
video keyframe (superseding the ffmpeg poster-frame idea). The worker hands an
adapter a TEXT-ONLY prompt and gets back image bytes plus a flat per-image
cost; the adapter never touches a video frame, and the prompt is built only
from text fields (dish name, cuisine, ingredient names).

**Hard Rule 7 (never fabricate food data):** the prompt is assembled ONLY from
text — dish name (en/original), cuisine_type, ingredient NAMES — NEVER from
quantities, steps, or pixel data. An illustration built from unprotectable
facts carries none of the source video's protected expression (the legal
synergy in planning/chefclaw-cover-and-retention-decisions.md §2).

Selection is config-driven and fail-closed, MIRRORING the extractor seam
(chefclaw/extractors/__init__.py): the safe default is the fake adapter (tests,
golden suite, zero spend/network); ``gemini`` requires an API key or raises a
typed ConfigError before any paid call could happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from chefclaw.errors import ConfigError

if TYPE_CHECKING:
    from chefclaw.config import Settings

__all__ = [
    "STYLE_PROMPT_V1",
    "STYLE_VERSION",
    "ImageGeneratorAdapter",
    "ImageResult",
    "build_illustration_prompt",
    "get_image_generator",
    "image_model_id",
]

# The versioned style block. Bumping the medium/palette/negatives ⇒ bump the
# version so a recipe's stored image_style_version records which look produced
# it (a future restyle can then target only the stale versions).
STYLE_VERSION = "cartoon-v1"

# The fixed style block prepended to every illustration prompt (V2-E Direction
# A "Midnight Kitchen" look). Negative constraints keep people/hands/text out —
# a clean single-dish card face.
STYLE_PROMPT_V1 = (
    "A warm, appetizing hand-illustrated cartoon of the finished dish, plated "
    "beautifully, top-down or three-quarter view, soft studio lighting, rich "
    "saturated food colors on a dark slate background, subtle steam. Cohesive "
    "children's-cookbook illustration style, gentle outlines, painterly "
    "shading. No text, no words, no logos, no watermarks, no hands, no people, "
    "no utensils in frame. Single centered dish. Square composition."
)

# How many ingredient names ride into the prompt — enough to characterize the
# dish, capped so the prompt stays a short subject line, not a recipe.
_MAX_INGREDIENT_NAMES = 10


@dataclass
class ImageResult:
    """What one illustration generation produced.

    ``cost_usd`` is a FLAT per-image price (image models bill per image, not
    per token) — the worker passes it straight to the spend ledger, never
    through the token-based ``spend.estimate_cost``.
    """

    image_bytes: bytes
    model_id: str
    cost_usd: Decimal


@runtime_checkable
class ImageGeneratorAdapter(Protocol):
    """The contract every illustration backend implements.

    Implementations must be stateless across calls and raise only errors from
    ``chefclaw.errors`` for pipeline-visible failures. NO retry loops inside an
    adapter — the worker owns budget checks and best-effort handling.
    """

    async def generate(self, prompt: str) -> ImageResult:
        """Generate one illustration from a text-only prompt."""
        ...


def build_illustration_prompt(document: dict) -> str:
    """Assemble the text-only illustration prompt for one recipe document.

    Hard Rule 7 — TEXT ONLY: dish name (en/original), cuisine_type, and
    ingredient NAMES. NEVER a quantity, NEVER a step, NEVER a video frame or
    pixel data. The style block is prepended so the look stays consistent
    across a library of wildly-varying source videos.
    """
    dish_name = document.get("dish_name") or {}
    name = dish_name.get("en") or dish_name.get("original") or "a cooked dish"

    subject_bits = [f"The dish is {name}."]
    original = dish_name.get("original")
    if original and original != name:
        subject_bits.append(f"Original name: {original}.")

    cuisine = document.get("cuisine_type")
    if cuisine:
        subject_bits.append(f"Cuisine: {cuisine}.")

    ingredient_names: list[str] = []
    for ingredient in document.get("ingredients") or []:
        if not isinstance(ingredient, dict):
            continue
        ing_name = ingredient.get("name") or {}
        # NAME sides only — never raw_text/quantity (those carry amounts).
        label = ing_name.get("en") or ing_name.get("original")
        if label:
            ingredient_names.append(label)
        if len(ingredient_names) >= _MAX_INGREDIENT_NAMES:
            break
    if ingredient_names:
        subject_bits.append("Key ingredients: " + ", ".join(ingredient_names) + ".")

    return STYLE_PROMPT_V1 + "\n\n" + " ".join(subject_bits)


def get_image_generator(settings: Settings) -> ImageGeneratorAdapter:
    """Config-selected image generator (``CHEFCLAW_IMAGE_GENERATOR``): fail closed.

    - ``fake`` (default) — a canned placeholder image, zero spend, safe
      everywhere (tests, golden suite, CI).
    - ``gemini`` — the real adapter; an empty ``GEMINI_API_KEY`` is a typed
      ConfigError HERE, before any paid image call could happen (fail-closed,
      mirrors the extractor seam).
    - anything else — ConfigError (a typo must never silently pick a backend).
    """
    name = settings.chefclaw_image_generator
    if name == "fake":
        from chefclaw.images.fake import FakeImageGenerator

        return FakeImageGenerator()
    if name == "gemini":
        if not settings.gemini_api_key:
            raise ConfigError(
                "CHEFCLAW_IMAGE_GENERATOR=gemini but GEMINI_API_KEY is empty — "
                "no paid image calls without explicit credentials (fail-closed)."
            )
        from chefclaw.images.gemini import GeminiImageGenerator

        return GeminiImageGenerator(settings)
    raise ConfigError(
        f"Unknown CHEFCLAW_IMAGE_GENERATOR value {name!r} — expected 'fake' or 'gemini'."
    )


def image_model_id(settings: Settings) -> str:
    """The model id the configured image generator would bill against — used
    for readouts. Never constructs an adapter (no key checks)."""
    if settings.chefclaw_image_generator == "gemini":
        return settings.gemini_image_model
    return f"{settings.chefclaw_image_generator}-image"
