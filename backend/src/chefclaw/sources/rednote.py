"""Rednote (Xiaohongshu) source adapter — XHS-Downloader sidecar (plan §3, §16.10).

Canonical id: the 24-hex note id from ``xiaohongshu.com/explore/<id>`` or
``/discovery/item/<id>``. Identity NEVER includes ``xsec_token`` or share
params (§16.1) — but the token is deliberately KEPT in ``fetch_url``:
spike-verified (2026-07-06, XHS-Downloader 2.7.stable) that detail fetch
FAILS for bare note-id URLs and succeeds — guest, no cookie — only when the
URL carries a valid ``xsec_token``. All other query params are stripped.
``xhslink.com`` short links are resolved by following redirects (the redirect
target carries a fresh token).

Fetch is TWO steps per the §3 sidecar contract (spike-verified against the
real sidecar API, ``ExtractParams``/``ExtractData`` in its OpenAPI schema):

1. ``POST {sidecar}/xhs/detail`` with ``{"url": ..., "download": false}``
   (plus ``"cookie"`` only when one is configured — GUEST TIER IS THE DEFAULT,
   §16.10; the main account never enters the pipeline). Response:
   ``{"message": str, "params": <echo>, "data": dict|null}`` with data keys
   like ``作品标题``/``作者昵称``/``作品类型``/``下载地址`` (list of URLs).
   SECURITY: ``params`` echoes the request INCLUDING the cookie — only
   ``data`` is ever parsed or stored; never log the raw response body.
2. The api downloads the returned media URL(s) ITSELF via httpx into
   ``dest_dir`` (the sidecar stays stateless; retention lives in one place),
   sending ``settings.xhs_user_agent`` when set.

The sidecar sits on the internal compose network only — its API is
unauthenticated by design, so it must never get a published host port.
"""

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from chefclaw import errors
from chefclaw.config import Settings
from chefclaw.sources import CanonicalRef, FetchedMedia

_NOTE_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-fA-F]{24})")
# Extracted verbatim from the raw query string (no decode/re-encode round
# trip — tokens contain '=' and the sidecar regexes them out of the URL).
_XSEC_TOKEN_RE = re.compile(r"[?&]xsec_token=([^&#]+)")
_XHS_HOSTS = frozenset({"xiaohongshu.com", "www.xiaohongshu.com"})
_SHORT_HOSTS = frozenset({"xhslink.com", "www.xhslink.com"})

# Signals in the sidecar's failure message that mean the session cookie is
# stale/invalid (vs. a generic fetch failure).
_COOKIE_SIGNALS = ("cookie", "登录", "login", "失效", "无效")
_RATE_SIGNALS = ("429", "频繁", "rate", "too many")

_DETAIL_TIMEOUT = 60.0
_MEDIA_TIMEOUT = 300.0


class RednoteSource:
    """SourceAdapter for xiaohongshu.com notes and xhslink.com short links."""

    platform = "rednote"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport  # test seam: httpx.MockTransport

    # ── matching ────────────────────────────────────────────────────────────

    def matches(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.netloc.lower()
        if host in _SHORT_HOSTS:
            return True
        return host in _XHS_HOSTS and bool(_NOTE_RE.search(parsed.path))

    # ── resolve (authoritative dedupe input — §16.1) ────────────────────────

    async def resolve(self, url: str) -> CanonicalRef:
        parsed = urlparse(url)
        if parsed.netloc.lower() in _SHORT_HOSTS:
            url = await self._follow_redirects(url)
            parsed = urlparse(url)

        match = _NOTE_RE.search(parsed.path)
        if match is None:
            raise errors.UnsupportedUrlError(f"no Rednote note id found in URL: {url!r}")
        note_id = match.group(1).lower()
        # Identity NEVER includes the token (§16.1) — but fetch needs it:
        # spike-verified that XHS rejects bare note-id URLs (guest or not),
        # so the pasted URL's token rides along in fetch_url only. Every
        # other query param (xsec_source, share params) is dropped.
        fetch_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        token_match = _XSEC_TOKEN_RE.search(url)
        if token_match:
            fetch_url += f"?xsec_token={token_match.group(1)}"
        return CanonicalRef(
            platform=self.platform,
            canonical_id=note_id,
            fetch_url=fetch_url,
        )

    async def _follow_redirects(self, url: str) -> str:
        headers = {}
        if self._settings.xhs_user_agent:
            headers["User-Agent"] = self._settings.xhs_user_agent
        try:
            async with httpx.AsyncClient(
                transport=self._transport, follow_redirects=True, timeout=30.0
            ) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise errors.DownloadFailedError(
                f"short-link resolution failed for {url!r}: {exc}"
            ) from exc
        return str(response.url)

    # ── fetch (two-step sidecar contract, §3) ───────────────────────────────

    async def fetch(self, ref: CanonicalRef, dest_dir: Path) -> FetchedMedia:
        base = self._settings.xhs_sidecar_url.rstrip("/")
        if not base:
            raise errors.ConfigError(
                "XHS_SIDECAR_URL is not set — the Rednote source is disabled "
                "(fail-closed; see docs/SERVICES.md)"
            )
        dest_dir.mkdir(parents=True, exist_ok=True)

        data = await self._sidecar_detail(base, ref)
        media_urls = self._media_urls(data, ref)

        paths: list[Path] = []
        async with httpx.AsyncClient(
            transport=self._transport, follow_redirects=True, timeout=_MEDIA_TIMEOUT
        ) as client:
            for index, media_url in enumerate(media_urls):
                paths.append(await self._download_media(client, media_url, ref, index, dest_dir))

        duration = _parse_duration(data.get("时长"))
        return FetchedMedia(
            video_path=paths[0],
            title=data.get("作品标题") or None,
            creator=data.get("作者昵称") or None,
            duration_seconds=duration,
            extra={"sidecar_data": data, "media_paths": [str(p) for p in paths]},
        )

    async def _sidecar_detail(self, base: str, ref: CanonicalRef) -> dict[str, Any]:
        """Step 1: ask the sidecar for note metadata + media URLs (no download)."""
        payload: dict[str, Any] = {"url": ref.fetch_url, "download": False}
        # Guest tier is the default (§16.10): only send a cookie if configured.
        if self._settings.xhs_cookie:
            payload["cookie"] = self._settings.xhs_cookie

        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_DETAIL_TIMEOUT
            ) as client:
                response = await client.post(f"{base}/xhs/detail", json=payload)
        except httpx.HTTPError as exc:
            raise errors.DownloadFailedError(f"xhs sidecar unreachable: {exc}") from exc

        if response.status_code == 429:
            raise errors.RateLimitedError("xhs sidecar reported throttling (HTTP 429)")
        if response.status_code >= 400:
            raise errors.DownloadFailedError(
                f"xhs sidecar returned HTTP {response.status_code}"
            )

        try:
            body = response.json()
        except ValueError:
            raise errors.DownloadFailedError(
                "xhs sidecar returned non-JSON response"
            ) from None
        if not isinstance(body, dict):
            raise errors.DownloadFailedError(
                "xhs sidecar returned a non-object JSON response"
            )

        data = body.get("data")
        if not data:
            raise self._map_failure_message(str(body.get("message", "")), ref)
        if not isinstance(data, dict):
            raise errors.DownloadFailedError(
                f"xhs sidecar returned malformed data for {ref.canonical_id} (not an object)"
            )
        return data

    def _map_failure_message(self, message: str, ref: CanonicalRef) -> errors.ChefclawError:
        lowered = message.lower()
        if any(signal in lowered for signal in _RATE_SIGNALS):
            return errors.RateLimitedError(f"rednote throttled {ref.canonical_id}: {message}")
        if any(signal in lowered for signal in _COOKIE_SIGNALS):
            if self._settings.xhs_cookie:
                return errors.CookiesExpiredError(
                    f"rednote session invalid for {ref.canonical_id}: {message} "
                    "(refresh per docs/RUNBOOK.md)"
                )
            # Guest tier (§16.10 tier 0): there is no session to refresh — the
            # note needs a login. Same error_type (the fix is still "configure
            # a cookie"), but the message must not claim a session existed.
            return errors.CookiesExpiredError(
                f"rednote note {ref.canonical_id} requires a login the guest tier "
                f"doesn't have: {message} (configure a hard-isolated throwaway "
                "cookie — tier 1, docs/RUNBOOK.md; never the main account)"
            )
        detail = message or "empty sidecar data"
        if "xsec_token" not in ref.fetch_url:
            # Spike-verified failure mode: XHS rejects bare note-id URLs.
            detail += " (URL had no xsec_token — paste the full share link)"
        return errors.DownloadFailedError(
            f"rednote fetch failed for {ref.canonical_id}: {detail}"
        )

    @staticmethod
    def _media_urls(data: dict[str, Any], ref: CanonicalRef) -> list[str]:
        raw = data.get("下载地址") or data.get("downloadUrl") or []
        if isinstance(raw, str):
            raw = [u for u in raw.split() if u]
        urls = [u for u in raw if isinstance(u, str) and u.startswith("http")]
        if not urls:
            raise errors.DownloadFailedError(
                f"sidecar returned no media URLs for {ref.canonical_id}"
            )
        return urls

    async def _download_media(
        self,
        client: httpx.AsyncClient,
        media_url: str,
        ref: CanonicalRef,
        index: int,
        dest_dir: Path,
    ) -> Path:
        """Step 2: the api downloads the media itself (sidecar stays stateless)."""
        headers = {}
        if self._settings.xhs_user_agent:
            headers["User-Agent"] = self._settings.xhs_user_agent
        suffix = _suffix_from_url(media_url)
        path = dest_dir / f"{ref.canonical_id}-{index}{suffix}"
        try:
            async with client.stream("GET", media_url, headers=headers) as response:
                if response.status_code == 429:
                    raise errors.RateLimitedError("rednote CDN throttled the media download")
                if response.status_code >= 400:
                    raise errors.DownloadFailedError(
                        f"media download failed (HTTP {response.status_code}): {media_url}"
                    )
                with path.open("wb") as out:
                    async for chunk in response.aiter_bytes():
                        out.write(chunk)
        except httpx.HTTPError as exc:
            raise errors.DownloadFailedError(
                f"media download failed for {media_url}: {exc}"
            ) from exc
        return path


def _suffix_from_url(media_url: str) -> str:
    path_suffix = Path(urlparse(media_url).path).suffix.lower()
    if path_suffix in (".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png", ".webp"):
        return path_suffix
    return ".mp4"


def _parse_duration(value: Any) -> int | None:
    """Parse the sidecar's duration field ('mm:ss' / 'hh:mm:ss' / seconds).

    Returns None when absent or unparseable — never guessed (Hard Rule 7
    discipline applies to metadata too).
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return int(text)
    parts = text.split(":")
    if all(re.fullmatch(r"\d+", p) for p in parts) and 2 <= len(parts) <= 3:
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return seconds
    return None
