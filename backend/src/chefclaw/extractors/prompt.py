"""The versioned extraction prompt, shared by every real extractor backend.

One prompt, one version stamp: Gemini and Qwen (fallback) run the SAME
faithful-capture instructions so a backend swap never silently changes what
"extraction" means. The version string rides into ``extraction_meta`` and the
spend ledger via :class:`~chefclaw.extractors.ExtractionUsage`.
"""

from importlib import resources

from chefclaw.covers import catalog_menu
from chefclaw.errors import ConfigError

PROMPT_VERSION = "v4"
_PROMPT_RESOURCE = "extract_v4.md"


def load_prompt() -> str:
    """Load the versioned extraction prompt shipped inside the package."""
    text = (
        resources.files("chefclaw").joinpath("prompts").joinpath(_PROMPT_RESOURCE).read_text(
            encoding="utf-8"
        )
    )
    if not text.strip():
        raise ConfigError(f"Extraction prompt {_PROMPT_RESOURCE!r} is empty — refusing paid calls.")
    return text


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


def with_cover_catalog(prompt: str) -> str:
    """Append the cover-sprite catalog menu (V2-F) so the model can pick a VALID
    ``cover_sprite_id``. The menu is appended at CALL time from the covers
    catalog (not baked into the prompt file) so it grows with the library with
    no prompt edit. Every real extractor backend appends it — the fake extractor
    returns canned dishes and never builds a prompt."""
    return (
        prompt
        + "\n\n## Cover sprite catalog — choose `cover_sprite_id` from these ids\n\n"
        + "Each line is `id | English name | 中文 name | tags`. Pick the ONE id "
        + "whose dish best matches this dish (same dish, else closest cuisine + "
        + "form). Copy the id EXACTLY; use `null` if nothing fits — never invent "
        + "an id.\n\n"
        + catalog_menu()
    )
