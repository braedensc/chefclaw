"""The versioned extraction prompt, shared by every real extractor backend.

One prompt, one version stamp: Gemini and Qwen (fallback) run the SAME
faithful-capture instructions so a backend swap never silently changes what
"extraction" means. The version string rides into ``extraction_meta`` and the
spend ledger via :class:`~chefclaw.extractors.ExtractionUsage`.
"""

from importlib import resources

from chefclaw.errors import ConfigError

PROMPT_VERSION = "v3"
_PROMPT_RESOURCE = "extract_v3.md"

# The escalation variant (V2-C, ADR 2026-07-07-cross-device-and-extractor-qa).
# IDENTICAL faithful-capture rules to v3, wrapped in a two-key envelope that adds
# a ``capture_quality.on_screen_text`` self-report so the Gemini adapter can tell
# when overlay text was unreadable at the base resolution and escalate. Used ONLY
# by the Gemini adapter when media-resolution escalation is enabled
# (GEMINI_MEDIA_RESOLUTION_MAX set); v3 stays the shared default for the
# no-escalation path and for the Qwen fallback (never exercised live).
ESCALATION_PROMPT_VERSION = "v4"
_ESCALATION_PROMPT_RESOURCE = "extract_v4.md"


def _load(resource: str) -> str:
    text = (
        resources.files("chefclaw").joinpath("prompts").joinpath(resource).read_text(
            encoding="utf-8"
        )
    )
    if not text.strip():
        raise ConfigError(f"Extraction prompt {resource!r} is empty — refusing paid calls.")
    return text


def load_prompt() -> str:
    """Load the versioned extraction prompt shipped inside the package."""
    return _load(_PROMPT_RESOURCE)


def load_escalation_prompt() -> str:
    """Load the v4 envelope prompt used by the resolution-escalation path."""
    return _load(_ESCALATION_PROMPT_RESOURCE)


def with_source_context(
    prompt: str, source_title: str | None, source_duration_seconds: int | None
) -> str:
    """Append the source-metadata hint block (title/duration) when present."""
    context_lines = []
    if source_title:
        context_lines.append(f"Source post/video title: {source_title}")
    if source_duration_seconds is not None:
        context_lines.append(f"Source video duration: {source_duration_seconds} seconds")
    if not context_lines:
        return prompt
    return prompt + "\n\n## Source context (metadata, not content)\n" + "\n".join(context_lines)
