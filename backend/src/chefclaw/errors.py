"""The typed error taxonomy — plan §4 + the §16.8 config-error amendment.

Each pipeline failure mode is a DISTINCT type surfaced DISTINCTLY (cheap happy
path, smart unhappy path). The worker maps these onto jobs.error_type verbatim
via ``.error_type``; the UI maps error_type onto actions (cookies_expired →
runbook link, interrupted → retry button, budget_exceeded → hard stop).

``duplicate_url`` is deliberately NOT here — a duplicate is control flow
(return the existing job/recipes), never an error.

Import-cycle note: ``chefclaw.extractors`` imports this module, so the
``ExtractionUsage`` references below are TYPE_CHECKING-only strings — errors
CARRY usage (duck-typed at runtime), they never import the extractors package.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chefclaw.extractors import ExtractionUsage


class ChefclawError(Exception):
    """Base for every typed pipeline error. ``error_type`` is the stable string
    stored on jobs rows and returned by the API — never rename one casually."""

    error_type: str = "unknown"
    retryable: bool = False  # may the worker re-attempt (within the attempt cap)?


class UnsupportedUrlError(ChefclawError):
    """No SourceAdapter matches the URL."""

    error_type = "unsupported_url"


class CookiesExpiredError(ChefclawError):
    """Platform session credentials are stale/invalid (Rednote 2–4wk expiry).
    Actionable: refresh per the runbook; NOT retryable — retrying spends
    attempts on a deterministic failure."""

    error_type = "cookies_expired"


class RateLimitedError(ChefclawError):
    """Platform or model API throttled us. Retryable with backoff — and every
    retry that reaches a paid call is budget-checked first.

    ``usage`` carries the attempt's token accounting when the model API
    surfaced usage before failing — the spend ledger records the real tokens
    instead of zeros (jobs ADR known-limitation fix, Phase 4)."""

    error_type = "rate_limited"
    retryable = True

    def __init__(self, message: str, usage: "ExtractionUsage | None" = None) -> None:
        super().__init__(message)
        self.usage = usage


class DownloadFailedError(ChefclawError):
    """Video/media fetch failed for a reason that isn't cookies or throttling."""

    error_type = "download_failed"
    retryable = True


class ExtractionFailedError(ChefclawError):
    """The model call itself failed (or returned unusable output). Retryable —
    the worker may re-attempt with an adjusted prompt, budget-checked.

    ``usage`` carries the attempt's token accounting when the model API
    surfaced usage before failing (e.g. it billed a response we could not
    parse) — the spend ledger records the real tokens instead of zeros."""

    error_type = "extraction_failed"
    retryable = True

    def __init__(
        self,
        message: str,
        raw_text: str | None = None,
        usage: "ExtractionUsage | None" = None,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text  # full raw model text, preserved for debugging
        self.usage = usage


class ValidationFailedError(ChefclawError):
    """Model output did not validate against the recipe document schema. The
    raw output is preserved for debugging (never silently 'fixed' — Hard Rule 7)."""

    error_type = "validation_failed"

    def __init__(self, message: str, raw_output: object = None) -> None:
        super().__init__(message)
        self.raw_output = raw_output


class InterruptedError_(ChefclawError):
    """The api restarted mid-job (docker compose watch does this constantly).
    Requires an explicit human retry click — NEVER auto-re-run paid work."""

    error_type = "interrupted"


class BudgetExceededError(ChefclawError):
    """Monthly budget or daily attempt cap reached. Hard stop, no retry."""

    error_type = "budget_exceeded"


class ConfigError(ChefclawError):
    """Cost-guardrail config unset/unparseable ⇒ NO paid calls (fail-closed,
    plan §16.8). Also raised for other unusable configuration."""

    error_type = "config_error"


class UploadTooLargeError(ChefclawError):
    """A tier-2 file upload exceeds MAX_UPLOAD_MB. Not retryable — the same
    bytes will always be too big. Surfaced at request time as a 413; the cap
    exists so an authed client cannot fill the server's disk."""

    error_type = "upload_too_large"
