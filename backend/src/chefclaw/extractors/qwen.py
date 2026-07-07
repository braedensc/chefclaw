"""QwenExtractor — the config-flagged fallback (plan §3: Qwen3-VL family via
DashScope's OpenAI-compatible mode), selected with ``CHEFCLAW_EXTRACTOR=qwen``.

API shape (verified against Alibaba Cloud Model Studio docs, 2026-07-06 —
web-verified only, NEVER exercised against the live endpoint from this repo):

- ``POST {DASHSCOPE_BASE_URL}/chat/completions`` with
  ``Authorization: Bearer $DASHSCOPE_API_KEY`` (OpenAI-compatible mode).
- Video rides as a user-message content item
  ``{"type": "video_url", "video_url": {"url": …}}`` (docs place the optional
  ``fps`` frame-sampling knob as a SIBLING of ``video_url``; we omit it and
  take the documented default of 2.0).
- Response: ``choices[0].message.content`` (string) +
  ``usage.prompt_tokens`` / ``usage.completion_tokens``.
- Errors: HTTP status + ``{"error": {"message", "type", "code"}}``.

UNVERIFIED-LIVE (marked per plan §3/§10 — confirm on first real use, AFTER the
human data-governance/region review recorded in docs/SERVICES.md):
- Base64 ``data:`` URLs are the documented URL form for media inputs and the
  only way to send a LOCAL file through compatible mode (the ``file://`` form
  is DashScope-native-SDK-only), but the docs demonstrate Base64 for images —
  video-specific Base64 acceptance and its exact size cap are not documented.
  ``_MAX_VIDEO_BYTES`` is therefore a conservative in-code guard, not a
  documented limit.
- The default model id (``qwen3-vl-plus``) — model catalog moves fast; it is
  config (``DASHSCOPE_MODEL``), never trusted as current.

Same contract as Gemini: no retries here (the worker owns attempts + budget
gates), raw output is parsed but never validated or repaired (Hard Rule 7),
and parse failures carry token usage so the ledger records real spend.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from chefclaw.errors import ConfigError, ExtractionFailedError, RateLimitedError
from chefclaw.extractors import ExtractionOutcome, ExtractionUsage
from chefclaw.extractors.prompt import (
    PROMPT_VERSION,
    load_prompt,
    with_cover_catalog,
    with_source_context,
)

if TYPE_CHECKING:
    from chefclaw.config import Settings

__all__ = ["QwenExtractor"]

# Faithful capture, not creativity — same temperature as the Gemini adapter.
_TEMPERATURE = 0.1

_RAW_SNIPPET_CHARS = 500  # how much raw text goes into the error MESSAGE (full in .raw_text)

# UNVERIFIED-LIVE size guard (see module docstring): refuse to build a request
# whose Base64 body would plausibly exceed the endpoint's request cap. The
# refusal is DETERMINISTIC — it must not burn the job's paid-retry attempts.
_MAX_VIDEO_BYTES = 64 * 1024 * 1024


class QwenExtractor:
    """ExtractorAdapter backed by Qwen via DashScope OpenAI-compatible mode."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if not settings.dashscope_api_key:
            # get_extractor also gates this; kept here so a directly-built
            # adapter can never fire a keyless (mis-routed) request.
            raise ConfigError(
                "CHEFCLAW_EXTRACTOR=qwen but DASHSCOPE_API_KEY is empty — "
                "no paid calls without explicit credentials (fail-closed)."
            )
        if not settings.dashscope_model:
            raise ConfigError("DASHSCOPE_MODEL is empty — the qwen model id must be configured.")
        self._api_key = settings.dashscope_api_key
        self._model_id = settings.dashscope_model  # config string, never hardcoded
        self._base_url = settings.dashscope_base_url.rstrip("/")
        self._prompt = load_prompt()
        # Injectable for tests; None means one short-lived client per extract().
        self._client = client

    async def extract(
        self,
        video_path: Path,
        source_title: str | None,
        source_duration_seconds: int | None,
    ) -> ExtractionOutcome:
        payload = self._build_payload(video_path, source_title, source_duration_seconds)
        if self._client is not None:
            data = await self._post(self._client, payload)
        else:
            # No client-side read timeout: the worker owns the per-stage
            # deadline (asyncio.wait_for) and cancels us — same division of
            # labor as the Gemini adapter's poll loop.
            async with httpx.AsyncClient(timeout=None) as client:
                data = await self._post(client, payload)
        return self._parse_response(data)

    # ── request ──────────────────────────────────────────────────────────────

    def _build_payload(
        self,
        video_path: Path,
        source_title: str | None,
        source_duration_seconds: int | None,
    ) -> dict[str, Any]:
        # stat BEFORE read: the refusal must not first load a multi-GiB video
        # into memory just to reject it.
        video_size = video_path.stat().st_size
        if video_size > _MAX_VIDEO_BYTES:
            err = ExtractionFailedError(
                f"video is {video_size} bytes — over the {_MAX_VIDEO_BYTES}-byte "
                "Base64-request guard for the DashScope compatible-mode endpoint."
            )
            err.retryable = False  # deterministic: retrying cannot shrink the file
            raise err
        video_bytes = video_path.read_bytes()
        mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
        data_url = f"data:{mime_type};base64,{base64.b64encode(video_bytes).decode('ascii')}"
        prompt = with_cover_catalog(
            with_source_context(self._prompt, source_title, source_duration_seconds)
        )
        return {
            "model": self._model_id,
            "temperature": _TEMPERATURE,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "video_url", "video_url": {"url": data_url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

    async def _post(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
        # Transport-level errors (httpx.TransportError etc.) deliberately leak
        # untyped: the worker fail-closes them (terminal + attempt ledgered).
        response = await client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
        )
        if response.status_code != 200:
            raise self._map_http_error(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise ExtractionFailedError(
                f"DashScope returned a 200 with a non-JSON body ({exc}); "
                f"body starts: {response.text[:_RAW_SNIPPET_CHARS]!r}",
                raw_text=response.text,
            ) from exc
        if not isinstance(data, dict):
            raise ExtractionFailedError(
                "DashScope returned a 200 whose JSON body is not an object "
                f"(got {type(data).__name__})."
            )
        return data

    def _map_http_error(self, response: httpx.Response) -> Exception:
        """Map an OpenAI-compatible error response onto the typed taxonomy."""
        detail = ""
        try:
            error = response.json().get("error") or {}
            detail = f"{error.get('code', '')}: {error.get('message', '')}"
        except ValueError:
            detail = response.text[:_RAW_SNIPPET_CHARS]
        status = response.status_code
        if status == 429:
            return RateLimitedError(f"DashScope API throttled us ({status}): {detail}")
        if status in (401, 403):
            return ConfigError(
                f"DashScope API rejected our credentials ({status}): {detail} — "
                "check DASHSCOPE_API_KEY."
            )
        return ExtractionFailedError(f"DashScope API call failed ({status}): {detail}")

    # ── response ─────────────────────────────────────────────────────────────

    def _usage_from_body(self, data: dict[str, Any]) -> ExtractionUsage | None:
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return None
        details = usage.get("completion_tokens_details")
        reasoning = details.get("reasoning_tokens", 0) if isinstance(details, dict) else 0
        return ExtractionUsage(
            model_id=self._model_id,
            prompt_version=PROMPT_VERSION,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            tokens_thinking=int(reasoning or 0),
        )

    def _parse_response(self, data: dict[str, Any]) -> ExtractionOutcome:
        usage = self._usage_from_body(data)

        try:
            raw_text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ExtractionFailedError(
                "DashScope response carried no choices[0].message.content to parse.",
                usage=usage,
            ) from None
        if not isinstance(raw_text, str):
            raise ExtractionFailedError(
                f"DashScope message content is not a string (got {type(raw_text).__name__}).",
                usage=usage,
            )

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ExtractionFailedError(
                f"Qwen returned non-JSON output ({exc}); "
                f"raw text starts: {raw_text[:_RAW_SNIPPET_CHARS]!r}",
                raw_text=raw_text,  # full raw output preserved for debugging
                usage=usage,
            ) from exc
        if not isinstance(parsed, list):
            raise ExtractionFailedError(
                "Qwen returned JSON but not the required top-level array of dishes "
                f"(got {type(parsed).__name__}); "
                f"raw text starts: {raw_text[:_RAW_SNIPPET_CHARS]!r}",
                raw_text=raw_text,
                usage=usage,
            )

        warnings: list[str] = []
        if usage is None:
            warnings.append("DashScope response carried no usage — tokens recorded as 0.")
            usage = ExtractionUsage(
                model_id=self._model_id,
                prompt_version=PROMPT_VERSION,
                tokens_in=0,
                tokens_out=0,
                tokens_thinking=0,
            )

        return ExtractionOutcome(dishes=parsed, usage=usage, warnings=warnings)
