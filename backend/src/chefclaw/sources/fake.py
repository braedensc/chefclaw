"""FakeSource — the config-selectable test double (plan §16.9).

The worker tests and the LOCAL-ONLY golden paste-to-card suite depend on it:
canned CanonicalRef/FetchedMedia plus ergonomic failure injection (raise any
taxonomy error on demand, optionally only for the first N calls — exactly what
retry/backoff tests need). Never fetches anything real.
"""

from pathlib import Path

from chefclaw.sources import CanonicalRef, FetchedMedia


def _as_exception(error: BaseException | type[BaseException]) -> BaseException:
    return error() if isinstance(error, type) else error


class _Failure:
    """An injected failure: raise ``error`` on each call, ``times`` times
    (None = every call, forever)."""

    def __init__(self, error: BaseException | type[BaseException], times: int | None) -> None:
        self.error = error
        self.remaining = times

    def fire(self) -> None:
        if self.remaining is None:
            raise _as_exception(self.error)
        if self.remaining > 0:
            self.remaining -= 1
            raise _as_exception(self.error)


class FakeSource:
    """Configurable canned SourceAdapter.

    Usage::

        fake = FakeSource(canonical_id="fake-abc")
        fake.fail_fetch(errors.RateLimitedError("throttled"), times=2)  # then succeeds
        fake.fail_resolve(errors.UnsupportedUrlError)                    # forever

    Calls are recorded on ``resolve_calls`` / ``fetch_calls`` for assertions.
    ``fetch()`` writes ``media_bytes`` to a real file in ``dest_dir`` so
    downstream code always gets an existing ``video_path``.
    """

    def __init__(
        self,
        *,
        platform: str = "fake",
        canonical_id: str = "fake-0000000001",
        match_prefixes: tuple[str, ...] = ("fake://", "https://fake.example/"),
        ref: CanonicalRef | None = None,
        title: str | None = "Fake cooking video",
        creator: str | None = "fake-creator",
        duration_seconds: int | None = 300,
        media_bytes: bytes = b"not really a video",
        extra: dict | None = None,
    ) -> None:
        self.platform = platform
        self.canonical_id = canonical_id
        self.match_prefixes = match_prefixes
        self.ref = ref
        self.title = title
        self.creator = creator
        self.duration_seconds = duration_seconds
        self.media_bytes = media_bytes
        self.extra = extra if extra is not None else {"fake": True}

        self.resolve_calls: list[str] = []
        self.fetch_calls: list[CanonicalRef] = []
        self._resolve_failure: _Failure | None = None
        self._fetch_failure: _Failure | None = None

    # ── failure injection ───────────────────────────────────────────────────

    def fail_resolve(
        self, error: BaseException | type[BaseException], *, times: int | None = None
    ) -> "FakeSource":
        """Make resolve() raise ``error`` (``times`` calls; None = always)."""
        self._resolve_failure = _Failure(error, times)
        return self

    def fail_fetch(
        self, error: BaseException | type[BaseException], *, times: int | None = None
    ) -> "FakeSource":
        """Make fetch() raise ``error`` (``times`` calls; None = always)."""
        self._fetch_failure = _Failure(error, times)
        return self

    # ── SourceAdapter surface ───────────────────────────────────────────────

    def matches(self, url: str) -> bool:
        return url.startswith(self.match_prefixes)

    async def resolve(self, url: str) -> CanonicalRef:
        self.resolve_calls.append(url)
        if self._resolve_failure is not None:
            self._resolve_failure.fire()
        if self.ref is not None:
            return self.ref
        return CanonicalRef(
            platform=self.platform, canonical_id=self.canonical_id, fetch_url=url
        )

    async def fetch(self, ref: CanonicalRef, dest_dir: Path) -> FetchedMedia:
        self.fetch_calls.append(ref)
        if self._fetch_failure is not None:
            self._fetch_failure.fire()
        dest_dir.mkdir(parents=True, exist_ok=True)
        video_path = dest_dir / f"{ref.canonical_id}.mp4"
        video_path.write_bytes(self.media_bytes)
        return FetchedMedia(
            video_path=video_path,
            title=self.title,
            creator=self.creator,
            duration_seconds=self.duration_seconds,
            extra=dict(self.extra),
        )
