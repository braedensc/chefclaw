"""SourceAdapter contract + registry (plan §2.3, §16.1, §16.10).

Every video platform is an adapter behind this small, documented interface —
adding a platform is adding an adapter, never a refactor.

The contract, in pipeline order:

1. ``matches(url)`` — cheap, synchronous, no network. Used by
   :func:`resolve_source` to pick the adapter for a pasted URL.
2. ``resolve(url)`` — network-light normalization (short-link redirects, id
   extraction). Returns a :class:`CanonicalRef`. **This is the AUTHORITATIVE
   dedupe input (§16.1):** dedupe keys on ``(platform, canonical_id)``, never
   the raw pasted URL — b23.tv short links, tracking params, and Rednote's
   per-share ``xsec_token`` all alias the same content. The paid model call is
   gated on the canonical-id check *after* resolution; the raw URL is kept as
   provenance only.
3. ``fetch(ref, dest_dir)`` — the heavy download, into a caller-owned
   directory (the worker decides scratch vs. retained archive, not the
   adapter).

RESERVED capability slot (§2.3, deliberately unimplemented): ``list_saved()``
— enumerate the authenticated user's saved/favorited posts for the future
bulk-import feature (§9 backlog). Adapters MUST NOT structurally assume
one-URL-in; when the feature lands (behind its own ADR: throttling +
review-queue UX), it arrives as an optional method on this Protocol, not a
redesign.

:class:`~chefclaw.sources.localfile.LocalFileSource` (§16.10 tier 2) is
invoked explicitly by the upload path via ``ingest()`` — it is never
URL-matched and is not registered with :func:`resolve_source`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from chefclaw import errors

__all__ = [
    "CanonicalRef",
    "FetchedMedia",
    "SourceAdapter",
    "resolve_source",
]


@dataclass(frozen=True)
class CanonicalRef:
    """Canonical identity of one piece of source content (§16.1).

    ``platform`` + ``canonical_id`` is the dedupe key (matches the
    ``UNIQUE(platform, canonical_id, dish_index)`` constraint). ``fetch_url``
    is the cleaned URL the adapter's own ``fetch()`` knows how to download —
    it is an adapter-internal detail, not provenance (provenance is the raw
    pasted URL, stored by the caller).
    """

    platform: str
    canonical_id: str
    fetch_url: str


@dataclass
class FetchedMedia:
    """Result of a successful ``fetch()``: a local video file + the metadata
    the platform actually stated (fields are None when the platform didn't
    say — never guessed; Hard Rule 7 applies to metadata too)."""

    video_path: Path
    title: str | None
    creator: str | None
    duration_seconds: int | None
    extra: dict = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """The per-platform contract. See the module docstring for the pipeline
    order, the §16.1 dedupe rule, and the reserved ``list_saved()`` slot."""

    platform: str

    def matches(self, url: str) -> bool:
        """Cheap, sync, offline: does this adapter own this URL?"""
        ...

    async def resolve(self, url: str) -> CanonicalRef:
        """Normalize to canonical identity — the authoritative dedupe input.

        Raises :class:`chefclaw.errors.UnsupportedUrlError` if the URL turns
        out not to contain this platform's native id after all, and
        :class:`chefclaw.errors.DownloadFailedError` (retryable) when the
        network-dependent part of normalization — short-link redirect
        following — fails.
        """
        ...

    async def fetch(self, ref: CanonicalRef, dest_dir: Path) -> FetchedMedia:
        """Download the media into ``dest_dir``. Raises the typed taxonomy:
        CookiesExpiredError / RateLimitedError / DownloadFailedError /
        ConfigError."""
        ...


def resolve_source(url: str, adapters: Sequence[SourceAdapter]) -> SourceAdapter:
    """Pick the adapter that owns ``url``; first match wins.

    Raises :class:`chefclaw.errors.UnsupportedUrlError` when no adapter
    matches. ``LocalFileSource`` is deliberately never registered here — the
    upload path invokes it explicitly.
    """
    for adapter in adapters:
        if adapter.matches(url):
            return adapter
    raise errors.UnsupportedUrlError(f"no source adapter matches URL: {url!r}")
