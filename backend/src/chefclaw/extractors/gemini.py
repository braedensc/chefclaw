"""GeminiExtractor — Gemini video extraction via the Files API (plan §3, §16.8).

Flow: upload the video → poll until ACTIVE → one generate_content call with
thinking DISABLED (transcription-style extraction; the real cost lever), JSON
response mime type, low temperature — then parse the raw dish array and hand it
back UNVALIDATED (the documents layer validates; Hard Rule 7 forbids repair).

No retry loops here: the worker owns attempts, budget checks, and per-stage
timeouts. Errors are mapped onto the typed taxonomy so the worker can act:
429/quota → RateLimitedError (retryable), auth → ConfigError (deterministic,
don't burn attempts), everything else API-side → ExtractionFailedError.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from chefclaw.errors import ConfigError, ExtractionFailedError, RateLimitedError
from chefclaw.extractors import ExtractionOutcome, ExtractionUsage
from chefclaw.extractors.prompt import (
    PROMPT_VERSION,
    load_prompt,
    with_cover_catalog,
    with_source_context,
)

__all__ = ["PROMPT_VERSION", "GeminiExtractor", "load_prompt"]

# Config string → SDK enum. Unknown values are a ConfigError (fail-closed, §16.8),
# never a silent default: media resolution is a cost & quality knob.
_MEDIA_RESOLUTIONS: dict[str, genai_types.MediaResolution] = {
    "low": genai_types.MediaResolution.MEDIA_RESOLUTION_LOW,
    "medium": genai_types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
    "high": genai_types.MediaResolution.MEDIA_RESOLUTION_HIGH,
}

# Faithful capture, not creativity — low temperature by design (plan §3).
_TEMPERATURE = 0.1

_RAW_SNIPPET_CHARS = 500  # how much raw text goes into the error MESSAGE (full in .raw_text)

if TYPE_CHECKING:
    from chefclaw.config import Settings


def _map_api_error(exc: genai_errors.APIError) -> Exception:
    """Map a google-genai APIError onto the typed taxonomy."""
    status = (exc.status or "").upper()
    if exc.code == 429 or status == "RESOURCE_EXHAUSTED":
        err: Exception = RateLimitedError(
            f"Gemini API throttled us ({exc.code} {status}): {exc.message}"
        )
    elif exc.code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
        err = ConfigError(
            f"Gemini API rejected our credentials ({exc.code} {status}): {exc.message} — "
            "check GEMINI_API_KEY."
        )
    else:
        err = ExtractionFailedError(f"Gemini API call failed ({exc.code} {status}): {exc.message}")
    return err


class GeminiExtractor:
    """ExtractorAdapter backed by Gemini (google-genai SDK, Files API upload)."""

    def __init__(
        self,
        settings: Settings,
        client: genai.Client | None = None,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        resolution_name = settings.gemini_media_resolution
        try:
            self._media_resolution = _MEDIA_RESOLUTIONS[resolution_name]
        except KeyError:
            raise ConfigError(
                f"Unknown GEMINI_MEDIA_RESOLUTION value {resolution_name!r} — "
                f"expected one of {sorted(_MEDIA_RESOLUTIONS)}."
            ) from None
        self._model_id = settings.gemini_model  # config string, never hardcoded
        self._prompt = load_prompt()
        # Injectable for tests; constructing a real client makes no network calls.
        if client is None:
            client = genai.Client(api_key=settings.gemini_api_key)
        self._client = client
        self._poll_interval_seconds = poll_interval_seconds

    async def extract(
        self,
        video_path: Path,
        source_title: str | None,
        source_duration_seconds: int | None,
    ) -> ExtractionOutcome:
        uploaded = await self._upload_and_wait_active(video_path)
        try:
            response = await self._generate(uploaded, source_title, source_duration_seconds)
        finally:
            await self._delete_best_effort(uploaded)
        return self._parse_response(response)

    # ── stages ──────────────────────────────────────────────────────────────

    async def _upload_and_wait_active(self, video_path: Path) -> genai_types.File:
        try:
            uploaded = await self._client.aio.files.upload(file=video_path)
        except genai_errors.APIError as exc:
            raise _map_api_error(exc) from exc

        try:
            while uploaded.state == genai_types.FileState.PROCESSING:
                # No deadline here — the worker owns the per-stage timeout and
                # cancels us; each loop iteration is an awaitable cancel point.
                await asyncio.sleep(self._poll_interval_seconds)
                uploaded = await self._client.aio.files.get(name=uploaded.name)
            if uploaded.state != genai_types.FileState.ACTIVE:
                error_detail = getattr(uploaded.error, "message", None) or uploaded.state
                raise ExtractionFailedError(
                    f"Gemini Files API could not process the video: {error_detail}"
                )
        except genai_errors.APIError as exc:
            await self._delete_best_effort(uploaded)
            raise _map_api_error(exc) from exc
        except BaseException:
            # Covers ExtractionFailedError above AND worker cancellation (the
            # per-stage timeout cancels us mid-poll — the designed deadline
            # path) plus any unexpected error: never leak the uploaded file.
            await self._delete_best_effort(uploaded)
            raise
        return uploaded

    async def _generate(
        self,
        uploaded: genai_types.File,
        source_title: str | None,
        source_duration_seconds: int | None,
    ) -> genai_types.GenerateContentResponse:
        prompt = with_cover_catalog(
            with_source_context(self._prompt, source_title, source_duration_seconds)
        )

        config = genai_types.GenerateContentConfig(
            temperature=_TEMPERATURE,
            response_mime_type="application/json",
            # Transcription-style extraction: thinking OFF is the cost lever (§3).
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            media_resolution=self._media_resolution,
        )
        try:
            return await self._client.aio.models.generate_content(
                model=self._model_id,
                contents=[uploaded, prompt],
                config=config,
            )
        except genai_errors.APIError as exc:
            raise _map_api_error(exc) from exc

    def _usage_from_response(
        self, response: genai_types.GenerateContentResponse
    ) -> ExtractionUsage | None:
        """Token accounting from usage_metadata, or None when the SDK carried
        none. Failures attach this to the raised error so the ledger records
        real tokens for a billed-but-unusable response (Phase 4 fix)."""
        usage_meta = response.usage_metadata
        if usage_meta is None:
            return None
        return ExtractionUsage(
            model_id=self._model_id,
            prompt_version=PROMPT_VERSION,
            tokens_in=usage_meta.prompt_token_count or 0,
            tokens_out=usage_meta.candidates_token_count or 0,
            # Thinking is disabled; the SDK reports thoughts_token_count as
            # None/absent then — record what it reports, defaulting to 0.
            tokens_thinking=usage_meta.thoughts_token_count or 0,
        )

    def _parse_response(
        self, response: genai_types.GenerateContentResponse
    ) -> ExtractionOutcome:
        usage = self._usage_from_response(response)

        raw_text = response.text
        if raw_text is None:
            raise ExtractionFailedError("Gemini returned no text content to parse.", usage=usage)

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ExtractionFailedError(
                f"Gemini returned non-JSON output ({exc}); "
                f"raw text starts: {raw_text[:_RAW_SNIPPET_CHARS]!r}",
                raw_text=raw_text,  # full raw output preserved for debugging
                usage=usage,
            ) from exc
        if not isinstance(parsed, list):
            raise ExtractionFailedError(
                "Gemini returned JSON but not the required top-level array of dishes "
                f"(got {type(parsed).__name__}); "
                f"raw text starts: {raw_text[:_RAW_SNIPPET_CHARS]!r}",
                raw_text=raw_text,
                usage=usage,
            )

        warnings: list[str] = []
        if usage is None:
            warnings.append("Gemini response carried no usage_metadata — tokens recorded as 0.")
            usage = ExtractionUsage(
                model_id=self._model_id,
                prompt_version=PROMPT_VERSION,
                tokens_in=0,
                tokens_out=0,
                tokens_thinking=0,
            )

        return ExtractionOutcome(dishes=parsed, usage=usage, warnings=warnings)

    async def _delete_best_effort(self, uploaded: genai_types.File) -> None:
        """Files-API cleanup must never fail the extraction."""
        if not uploaded.name:
            return
        try:
            await self._client.aio.files.delete(name=uploaded.name)
        except Exception:  # noqa: BLE001 — best-effort by contract
            pass
