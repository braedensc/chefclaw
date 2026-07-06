"""ExtractorAdapter — the model-extraction seam (plan §2.3, §3).

Everything model-shaped sits behind this interface: the worker hands an adapter
a local video file and gets back RAW dish dicts plus token accounting. The
extractor NEVER validates or repairs model output — the documents layer owns
validation (Hard Rule 7: raw captures are preserved, never "fixed").

Selection is config-driven and fail-closed (§16.8): the safe default is the
fake adapter (tests, golden suite, no accidental spend); ``gemini`` requires an
API key or raises a typed ConfigError before any paid call could happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from chefclaw.errors import ConfigError

if TYPE_CHECKING:
    from chefclaw.config import Settings

__all__ = [
    "ExtractionOutcome",
    "ExtractionUsage",
    "ExtractorAdapter",
    "get_extractor",
]


@dataclass
class ExtractionUsage:
    """Token accounting for ONE model attempt — feeds the llm_spend ledger
    (written per attempt, including failures — plan §5/§10)."""

    model_id: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
    tokens_thinking: int


@dataclass
class ExtractionOutcome:
    """What one extraction attempt produced.

    ``dishes`` is the RAW model output, one dict per dish, exactly as parsed
    from the response JSON. No validation, no coercion, no defaulting happens
    here — the documents layer validates against the recipe schema and is the
    only place allowed to reject (never repair) the data.
    """

    dishes: list[dict]
    usage: ExtractionUsage
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class ExtractorAdapter(Protocol):
    """The contract every extraction backend implements.

    Implementations must be stateless across calls and raise only errors from
    ``chefclaw.errors`` for pipeline-visible failures. NO retry loops inside an
    adapter — the worker owns attempts, budget checks, and per-stage timeouts.
    """

    async def extract(
        self,
        video_path: Path,
        source_title: str | None,
        source_duration_seconds: int | None,
    ) -> ExtractionOutcome:
        """Extract recipe dishes from a local video file.

        ``source_title``/``source_duration_seconds`` are optional context from
        the source adapter, passed to the model as hints — never echoed into
        the output by the pipeline itself.
        """
        ...


def get_extractor(settings: Settings) -> ExtractorAdapter:
    """Config-selected extractor (``CHEFCLAW_EXTRACTOR``): fail closed.

    - ``fake`` (default) — canned fixtures, zero spend, safe everywhere.
    - ``gemini`` — the real adapter; an empty ``GEMINI_API_KEY`` is a typed
      ConfigError HERE, before anything is downloaded or uploaded (§16.8).
    - anything else — ConfigError (a typo must never silently pick a backend).
    """
    name = settings.chefclaw_extractor
    if name == "fake":
        from chefclaw.extractors.fake import FakeExtractor

        return FakeExtractor()
    if name == "gemini":
        if not settings.gemini_api_key:
            raise ConfigError(
                "CHEFCLAW_EXTRACTOR=gemini but GEMINI_API_KEY is empty — "
                "no paid calls without explicit credentials (fail-closed)."
            )
        from chefclaw.extractors.gemini import GeminiExtractor

        return GeminiExtractor(settings)
    raise ConfigError(
        f"Unknown CHEFCLAW_EXTRACTOR value {name!r} — expected 'fake' or 'gemini'."
    )
