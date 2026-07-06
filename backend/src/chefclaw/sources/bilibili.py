"""Bilibili source adapter — yt-dlp, anonymous-first (plan §3, §16.1).

Canonical id: ``{BV id}-p{part}`` — the ``?p=`` query param is SEMANTIC
(selects the part of a multi-part video); every other query param is tracking
noise and is stripped. b23.tv short links are resolved by following redirects
(no cookies) to the canonical BV URL.

Anonymous-first: no cookie is sent unless ``settings.bilibili_cookie`` is set.
Format is capped at 480p — LLM extraction doesn't need more, and the cap is
what makes anonymous access sufficient.
"""

import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from chefclaw import errors
from chefclaw.config import Settings
from chefclaw.sources import CanonicalRef, FetchedMedia

_BV_RE = re.compile(r"/(BV[0-9A-Za-z]{10})")
_BILI_HOSTS = frozenset({"bilibili.com", "www.bilibili.com", "m.bilibili.com"})
_SHORT_HOSTS = frozenset({"b23.tv", "www.b23.tv"})

_RATE_LIMIT_SIGNALS = ("412", "429", "rate limit", "too many requests", "precondition failed")

# The sync download callable: (fetch_url, ydl_opts) -> yt-dlp info dict.
Downloader = Callable[[str, dict[str, Any]], dict[str, Any]]


def _yt_dlp_download(url: str, opts: dict[str, Any]) -> dict[str, Any]:
    """Default downloader — the only place yt-dlp is touched (lazy import)."""
    import yt_dlp

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    if info is None:
        raise errors.DownloadFailedError(f"yt-dlp returned no info for {url}")
    # noplaylist=True normally yields a single entry, but be defensive.
    if "entries" in info:
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise errors.DownloadFailedError(f"yt-dlp returned an empty playlist for {url}")
        info = entries[0]
    return info


class BilibiliSource:
    """SourceAdapter for bilibili.com/video/BV… and b23.tv short links."""

    platform = "bilibili"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        downloader: Downloader | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport  # test seam: httpx.MockTransport
        self._downloader = downloader or _yt_dlp_download

    # ── matching ────────────────────────────────────────────────────────────

    def matches(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.netloc.lower()
        if host in _SHORT_HOSTS:
            return True
        return host in _BILI_HOSTS and bool(_BV_RE.search(parsed.path))

    # ── resolve (authoritative dedupe input — §16.1) ────────────────────────

    async def resolve(self, url: str) -> CanonicalRef:
        parsed = urlparse(url)
        if parsed.netloc.lower() in _SHORT_HOSTS and not _BV_RE.search(parsed.path):
            url = await self._follow_redirects(url)
            parsed = urlparse(url)

        match = _BV_RE.search(parsed.path)
        if match is None:
            raise errors.UnsupportedUrlError(f"no BV id found in URL: {url!r}")
        bvid = match.group(1)
        part = self._part_from_query(parsed.query)
        return CanonicalRef(
            platform=self.platform,
            canonical_id=f"{bvid}-p{part}",
            # ?p= is semantic and kept; every other param is tracking noise.
            fetch_url=f"https://www.bilibili.com/video/{bvid}/?p={part}",
        )

    @staticmethod
    def _part_from_query(query: str) -> int:
        values = parse_qs(query).get("p", [])
        if not values:
            return 1
        try:
            part = int(values[0])
        except ValueError:
            return 1
        return part if part >= 1 else 1

    async def _follow_redirects(self, url: str) -> str:
        """Resolve a b23.tv short link to its BV URL. No cookies, ever."""
        try:
            async with httpx.AsyncClient(
                transport=self._transport, follow_redirects=True, timeout=30.0
            ) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise errors.DownloadFailedError(
                f"short-link resolution failed for {url!r}: {exc}"
            ) from exc
        return str(response.url)

    # ── fetch ───────────────────────────────────────────────────────────────

    async def fetch(self, ref: CanonicalRef, dest_dir: Path) -> FetchedMedia:
        dest_dir.mkdir(parents=True, exist_ok=True)
        opts: dict[str, Any] = {
            # Prefer streams at or just below 480p; fall back upward only if
            # nothing smaller exists. LLM extraction doesn't need more.
            "format": "bv*+ba/b",
            "format_sort": ["res:480"],
            "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 2,
        }
        # Anonymous-first: only attach a cookie when one is configured.
        if self._settings.bilibili_cookie:
            opts["http_headers"] = {"Cookie": self._settings.bilibili_cookie}

        try:
            info = await asyncio.to_thread(self._downloader, ref.fetch_url, opts)
        except errors.ChefclawError:
            raise
        except Exception as exc:  # yt-dlp raises DownloadError/ExtractorError
            raise self._map_error(exc) from exc

        video_path = self._video_path_from_info(info, dest_dir)
        duration = info.get("duration")
        return FetchedMedia(
            video_path=video_path,
            title=info.get("title"),
            creator=info.get("uploader"),
            duration_seconds=int(round(duration)) if duration is not None else None,
            extra={
                "id": info.get("id"),
                "webpage_url": info.get("webpage_url"),
                "format": info.get("format"),
                "height": info.get("height"),
                "ext": info.get("ext"),
            },
        )

    @staticmethod
    def _map_error(exc: Exception) -> errors.ChefclawError:
        message = str(exc)
        lowered = message.lower()
        if any(signal in lowered for signal in _RATE_LIMIT_SIGNALS):
            return errors.RateLimitedError(f"bilibili throttled the download: {message}")
        return errors.DownloadFailedError(f"bilibili download failed: {message}")

    @staticmethod
    def _video_path_from_info(info: dict[str, Any], dest_dir: Path) -> Path:
        downloads = info.get("requested_downloads") or []
        if downloads and downloads[0].get("filepath"):
            return Path(downloads[0]["filepath"])
        # Fallback: reconstruct from the output template fields.
        if info.get("id") and info.get("ext"):
            candidate = dest_dir / f"{info['id']}.{info['ext']}"
            if candidate.exists():
                return candidate
        raise errors.DownloadFailedError("yt-dlp reported success but no output file was found")
