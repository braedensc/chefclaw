"""GeminiImageGenerator — cartoon dish illustrations via the google-genai SDK.

Flow: one generate_content call with the text-only illustration prompt against
the configured image model, an IMAGE response modality, then pull the first
inline image part out of the response. The FLAT per-image cost is config
(image models bill per image, not per token) and is passed straight to the
spend ledger by the worker.

**Hard Rule 7:** the prompt is built upstream from text fields only
(images.build_illustration_prompt) — this adapter never sees a video frame.

No retry loops here: the worker's illustration stage is best-effort and owns
budget checks. Errors are mapped onto the typed taxonomy: 429/quota →
RateLimitedError, auth → ConfigError (fail-closed — check GEMINI_API_KEY),
everything else → ImageGenerationFailedError.

This adapter is NOT exercised by the test suite (like the Qwen extractor
fallback, using it is a documented HUMAN precondition — re-confirm the model id
and flat cost at deploy). It must import cleanly and typecheck.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from chefclaw.errors import ConfigError, ImageGenerationFailedError, RateLimitedError
from chefclaw.images import ImageResult

__all__ = ["GeminiImageGenerator"]

if TYPE_CHECKING:
    from chefclaw.config import Settings


def _map_api_error(exc: genai_errors.APIError) -> Exception:
    """Map a google-genai APIError onto the typed taxonomy (mirrors the
    extractor's _map_api_error)."""
    status = (exc.status or "").upper()
    if exc.code == 429 or status == "RESOURCE_EXHAUSTED":
        return RateLimitedError(
            f"Gemini image API throttled us ({exc.code} {status}): {exc.message}"
        )
    if exc.code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
        return ConfigError(
            f"Gemini image API rejected our credentials ({exc.code} {status}): "
            f"{exc.message} — check GEMINI_API_KEY."
        )
    return ImageGenerationFailedError(
        f"Gemini image API call failed ({exc.code} {status}): {exc.message}"
    )


class GeminiImageGenerator:
    """ImageGeneratorAdapter backed by Gemini image generation (google-genai)."""

    def __init__(self, settings: Settings, client: genai.Client | None = None) -> None:
        self._model_id = settings.gemini_image_model  # config string, never hardcoded
        self._cost_usd = settings.gemini_image_cost_usd  # flat per-image price (config)
        # Injectable for tests; constructing a real client makes no network calls.
        if client is None:
            client = genai.Client(api_key=settings.gemini_api_key)
        self._client = client

    async def generate(self, prompt: str) -> ImageResult:
        config = genai_types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model_id,
                contents=[prompt],
                config=config,
            )
        except genai_errors.APIError as exc:
            raise _map_api_error(exc) from exc

        image_bytes = _first_image_bytes(response)
        if image_bytes is None:
            raise ImageGenerationFailedError(
                "Gemini image response carried no inline image data."
            )
        return ImageResult(
            image_bytes=image_bytes,
            model_id=self._model_id,
            cost_usd=self._cost_usd,
        )


def _first_image_bytes(response: genai_types.GenerateContentResponse) -> bytes | None:
    """Pull the first inline image part's bytes out of the response, or None."""
    for candidate in response.candidates or []:
        content = candidate.content
        if content is None:
            continue
        for part in content.parts or []:
            inline = part.inline_data
            if inline is not None and inline.data:
                return inline.data
    return None
