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
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from chefclaw.errors import ConfigError, ExtractionFailedError, RateLimitedError
from chefclaw.extractors import ExtractionOutcome, ExtractionUsage
from chefclaw.extractors.prompt import (
    ESCALATION_PROMPT_VERSION,
    PROMPT_VERSION,
    load_escalation_prompt,
    load_prompt,
    with_cover_catalog,
    with_source_context,
)

__all__ = ["PROMPT_VERSION", "GeminiExtractor", "load_prompt"]

logger = logging.getLogger(__name__)

# Config string → SDK enum. Unknown values are a ConfigError (fail-closed, §16.8),
# never a silent default: media resolution is a cost & quality knob.
_MEDIA_RESOLUTIONS: dict[str, genai_types.MediaResolution] = {
    "low": genai_types.MediaResolution.MEDIA_RESOLUTION_LOW,
    "medium": genai_types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
    "high": genai_types.MediaResolution.MEDIA_RESOLUTION_HIGH,
}
# Low→high ordering for the escalation ceiling check (must cover every key above).
_RESOLUTION_ORDER = ("low", "medium", "high")

# The v5 envelope's ``capture_quality.on_screen_text`` value that triggers a
# one-shot escalation: the model saw overlay text it could not read reliably.
_TEXT_UNREADABLE = "unreadable"

# Faithful capture, not creativity — low temperature by design (plan §3).
_TEMPERATURE = 0.1

_RAW_SNIPPET_CHARS = 500  # how much raw text goes into the error MESSAGE (full in .raw_text)

if TYPE_CHECKING:
    from chefclaw.config import Settings


def _sum_usage(base: ExtractionUsage, escalated: ExtractionUsage) -> ExtractionUsage:
    """Combine the base + escalated calls' token counts into one usage row so
    the single spend-ledger row the worker writes reflects the true cost of the
    attempt. Both calls share the model id and prompt version (escalation reuses
    the same adapter), so those carry through from the escalated call."""
    return ExtractionUsage(
        model_id=escalated.model_id,
        prompt_version=escalated.prompt_version,
        tokens_in=base.tokens_in + escalated.tokens_in,
        tokens_out=base.tokens_out + escalated.tokens_out,
        tokens_thinking=base.tokens_thinking + escalated.tokens_thinking,
    )


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
        self._base_resolution_name = resolution_name

        # Optional one-shot escalation ceiling (V2-C). Empty = OFF (the default):
        # base resolution, the shared v4 prompt, one paid call — today's behavior
        # unchanged. Set ⇒ the v5 envelope prompt + a single higher-res retry when
        # the model reports unreadable on-screen text.
        self._escalate_to: genai_types.MediaResolution | None = None
        self._escalate_to_name: str | None = None
        max_name = settings.gemini_media_resolution_max
        if max_name:
            try:
                escalate_to = _MEDIA_RESOLUTIONS[max_name]
            except KeyError:
                raise ConfigError(
                    f"Unknown GEMINI_MEDIA_RESOLUTION_MAX value {max_name!r} — "
                    f"expected one of {sorted(_MEDIA_RESOLUTIONS)}."
                ) from None
            if _RESOLUTION_ORDER.index(max_name) <= _RESOLUTION_ORDER.index(resolution_name):
                raise ConfigError(
                    f"GEMINI_MEDIA_RESOLUTION_MAX ({max_name!r}) must be ABOVE the base "
                    f"GEMINI_MEDIA_RESOLUTION ({resolution_name!r}) to enable escalation."
                )
            self._escalate_to = escalate_to
            self._escalate_to_name = max_name

        self._model_id = settings.gemini_model  # config string, never hardcoded
        # The v5 envelope prompt carries the legibility self-report escalation
        # needs; without escalation we keep the shared v4 prompt byte-for-byte
        # (and the same version stamp), so the default path is unchanged.
        if self._escalate_to is not None:
            self._prompt = load_escalation_prompt()
            self._prompt_version = ESCALATION_PROMPT_VERSION
        else:
            self._prompt = load_prompt()
            self._prompt_version = PROMPT_VERSION
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
            response = await self._generate(
                uploaded, source_title, source_duration_seconds, self._media_resolution
            )
            outcome, on_screen_text = self._parse_response(response)
            # One-shot resolution escalation: the base extraction succeeded but
            # the model flagged overlay text it could not read at this
            # resolution — retry the SAME uploaded video once, higher (V2-C).
            if self._escalate_to is not None and on_screen_text == _TEXT_UNREADABLE:
                outcome = await self._escalate(
                    uploaded, source_title, source_duration_seconds, outcome
                )
        finally:
            await self._delete_best_effort(uploaded)
        return outcome

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
        media_resolution: genai_types.MediaResolution,
    ) -> genai_types.GenerateContentResponse:
        prompt = with_cover_catalog(
            with_source_context(self._prompt, source_title, source_duration_seconds)
        )

        config = genai_types.GenerateContentConfig(
            temperature=_TEMPERATURE,
            response_mime_type="application/json",
            # Transcription-style extraction: thinking OFF is the cost lever (§3).
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            media_resolution=media_resolution,
        )
        try:
            return await self._client.aio.models.generate_content(
                model=self._model_id,
                contents=[uploaded, prompt],
                config=config,
            )
        except genai_errors.APIError as exc:
            raise _map_api_error(exc) from exc

    async def _escalate(
        self,
        uploaded: genai_types.File,
        source_title: str | None,
        source_duration_seconds: int | None,
        base_outcome: ExtractionOutcome,
    ) -> ExtractionOutcome:
        """Retry the SAME already-uploaded video ONCE at the escalation ceiling
        (the model flagged unreadable on-screen text at the base resolution).

        Best-effort quality bump: the base extraction already succeeded, so a
        failed escalation must never lose it — any failure keeps the base result
        with a warning. On success the escalated dishes win and BOTH calls'
        tokens are summed into one usage row so the ledger reflects the real
        attempt cost (the worker writes a single spend row per extract())."""
        logger.info(
            "gemini media-resolution escalation: on-screen text unreadable at %s — "
            "retrying once at %s",
            self._base_resolution_name,
            self._escalate_to_name,
        )
        assert self._escalate_to is not None  # guarded by the caller
        try:
            response = await self._generate(
                uploaded, source_title, source_duration_seconds, self._escalate_to
            )
            escalated, _ = self._parse_response(response)
        except Exception as exc:  # noqa: BLE001 — never lose a good base result
            logger.warning(
                "gemini escalation retry failed (%s) — keeping the %s-resolution result",
                exc,
                self._base_resolution_name,
                exc_info=True,
            )
            base_outcome.warnings.append(
                f"media-resolution escalation to {self._escalate_to_name} failed "
                f"({type(exc).__name__}); kept the {self._base_resolution_name} result"
            )
            return base_outcome

        escalated.usage = _sum_usage(base_outcome.usage, escalated.usage)
        escalated.warnings = [
            *base_outcome.warnings,
            *escalated.warnings,
            f"media resolution escalated {self._base_resolution_name} → "
            f"{self._escalate_to_name} (on-screen text unreadable at the base resolution)",
        ]
        return escalated

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
            prompt_version=self._prompt_version,
            tokens_in=usage_meta.prompt_token_count or 0,
            tokens_out=usage_meta.candidates_token_count or 0,
            # Thinking is disabled; the SDK reports thoughts_token_count as
            # None/absent then — record what it reports, defaulting to 0.
            tokens_thinking=usage_meta.thoughts_token_count or 0,
        )

    def _parse_response(
        self, response: genai_types.GenerateContentResponse
    ) -> tuple[ExtractionOutcome, str | None]:
        """Parse a Gemini response into ``(outcome, on_screen_text)``. Tolerant
        of BOTH shapes: the v5 escalation envelope
        (``{"dishes": [...], "capture_quality": {"on_screen_text": ...}}``) and a
        bare v4 array. The second tuple element is the legibility self-report
        (``None`` for a bare array or a malformed ``capture_quality``) — the only
        thing the escalation decision reads."""
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

        dishes, on_screen_text = self._unwrap(parsed, raw_text, usage)

        warnings: list[str] = []
        if usage is None:
            warnings.append("Gemini response carried no usage_metadata — tokens recorded as 0.")
            usage = ExtractionUsage(
                model_id=self._model_id,
                prompt_version=self._prompt_version,
                tokens_in=0,
                tokens_out=0,
                tokens_thinking=0,
            )

        return ExtractionOutcome(dishes=dishes, usage=usage, warnings=warnings), on_screen_text

    def _unwrap(
        self, parsed: object, raw_text: str, usage: ExtractionUsage | None
    ) -> tuple[list, str | None]:
        """Extract the dish array + legibility signal from either output shape.
        A bare array is the v4 (and non-compliant v5) case → no signal. An
        envelope object must carry a ``dishes`` LIST; anything else is a hard
        ExtractionFailedError preserving the raw text (Hard Rule 7)."""
        if isinstance(parsed, list):
            return parsed, None
        if isinstance(parsed, dict) and isinstance(parsed.get("dishes"), list):
            on_screen_text: str | None = None
            capture_quality = parsed.get("capture_quality")
            if isinstance(capture_quality, dict):
                value = capture_quality.get("on_screen_text")
                if isinstance(value, str):
                    on_screen_text = value
            return parsed["dishes"], on_screen_text
        raise ExtractionFailedError(
            "Gemini returned JSON but not the required array of dishes (or "
            f"{{\"dishes\": [...]}} envelope); got {type(parsed).__name__}; "
            f"raw text starts: {raw_text[:_RAW_SNIPPET_CHARS]!r}",
            raw_text=raw_text,
            usage=usage,
        )

    async def _delete_best_effort(self, uploaded: genai_types.File) -> None:
        """Files-API cleanup must never fail the extraction."""
        if not uploaded.name:
            return
        try:
            await self._client.aio.files.delete(name=uploaded.name)
        except Exception:  # noqa: BLE001 — best-effort by contract
            pass
