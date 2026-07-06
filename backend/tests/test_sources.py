"""Source-adapter tests — no network, no database (CI constraint).

httpx is mocked via MockTransport handler injection; yt-dlp via the
downloader seam. Canonical-id behavior is the load-bearing part (§16.1):
these ids gate the paid model call.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from chefclaw import errors
from chefclaw.config import Settings
from chefclaw.sources import CanonicalRef, SourceAdapter, resolve_source
from chefclaw.sources.bilibili import BilibiliSource
from chefclaw.sources.fake import FakeSource
from chefclaw.sources.localfile import LocalFileSource
from chefclaw.sources.rednote import RednoteSource

BV = "BV1xx411c7mD"
NOTE_ID = "6684cf19000000001e01a4a4"


def settings(**overrides: Any) -> Settings:
    """Settings with every source field pinned — ambient env must not leak in."""
    values: dict[str, Any] = {
        "bilibili_cookie": "",
        "xhs_sidecar_url": "",
        "xhs_cookie": "",
        "xhs_user_agent": "",
        "chefclaw_fetch_proxy": "",
    }
    values.update(overrides)
    return Settings(**values)


PROXY = "socks5://proxy.test:1055"  # fake — the M-Deploy fetch-proxy knob


def spy_async_client(module_path: str, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record httpx.AsyncClient constructor kwargs inside an adapter module.

    A real `proxy=` kwarg mounts a proxy transport that would BYPASS the
    MockTransport test seam (and try the network), so the spy strips it after
    recording — the assertion target is the constructor kwargs themselves.
    """
    calls: list[dict[str, Any]] = []
    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        calls.append(dict(kwargs))
        kwargs.pop("proxy", None)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(f"{module_path}.httpx.AsyncClient", factory)
    return calls


def no_network_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network call: {request.url}")

    return httpx.MockTransport(handler)


def redirect_transport(location: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("b23.tv", "xhslink.com"):
            return httpx.Response(302, headers={"Location": location})
        return httpx.Response(200, text="<html></html>")

    return httpx.MockTransport(handler)


# ── registry ─────────────────────────────────────────────────────────────────


def test_resolve_source_picks_matching_adapter() -> None:
    bili = BilibiliSource(settings())
    red = RednoteSource(settings())
    url = f"https://www.bilibili.com/video/{BV}"
    assert resolve_source(url, [red, bili]) is bili


def test_resolve_source_unsupported_url() -> None:
    adapters = [BilibiliSource(settings()), RednoteSource(settings())]
    for url in (
        "https://www.youtube.com/watch?v=abc",
        "not a url at all",
        "ftp://bilibili.com/video/BV1xx411c7mD",
        "https://xiaohongshu.com/user/profile/123",
    ):
        with pytest.raises(errors.UnsupportedUrlError):
            resolve_source(url, adapters)


def test_adapters_satisfy_protocol() -> None:
    for adapter in (
        BilibiliSource(settings()),
        RednoteSource(settings()),
        FakeSource(),
    ):
        assert isinstance(adapter, SourceAdapter)
    # LocalFileSource is deliberately NOT a full SourceAdapter: its
    # fetch-equivalent is ingest() (explicit upload path, never URL-matched).
    assert not isinstance(LocalFileSource(Path("/nonexistent")), SourceAdapter)


def test_localfile_is_never_url_matched() -> None:
    local = LocalFileSource(Path("/nonexistent"))
    assert not local.matches("https://example.com/video.mp4")
    with pytest.raises(errors.UnsupportedUrlError):
        resolve_source("local://file-abc", [local])


# ── bilibili canonical ids (§16.1: BV id + part; ?p= is semantic) ────────────


@pytest.mark.parametrize(
    ("url", "canonical_id"),
    [
        (f"https://www.bilibili.com/video/{BV}", f"{BV}-p1"),
        (f"https://www.bilibili.com/video/{BV}/", f"{BV}-p1"),
        (f"https://bilibili.com/video/{BV}?p=3", f"{BV}-p3"),
        (f"https://m.bilibili.com/video/{BV}?p=2&spm_id_from=333.999.0.0", f"{BV}-p2"),
        # Tracking params are noise; only ?p= is semantic.
        (
            f"https://www.bilibili.com/video/{BV}?spm_id_from=333.999&vd_source=abc123",
            f"{BV}-p1",
        ),
        # Unparseable ?p= degrades to part 1, never an error.
        (f"https://www.bilibili.com/video/{BV}?p=abc", f"{BV}-p1"),
        (f"https://www.bilibili.com/video/{BV}?p=0", f"{BV}-p1"),
    ],
)
async def test_bilibili_canonical_id(url: str, canonical_id: str) -> None:
    source = BilibiliSource(settings(), transport=no_network_transport())
    ref = await source.resolve(url)
    assert ref == CanonicalRef(
        platform="bilibili",
        canonical_id=canonical_id,
        fetch_url=f"https://www.bilibili.com/video/{BV}/?p={canonical_id.rsplit('p', 1)[1]}",
    )


async def test_bilibili_b23_short_link_follows_redirect() -> None:
    target = f"https://www.bilibili.com/video/{BV}?p=2&share_source=copy_web"
    source = BilibiliSource(settings(), transport=redirect_transport(target))
    ref = await source.resolve("https://b23.tv/abc123")
    assert ref.canonical_id == f"{BV}-p2"
    assert "share_source" not in ref.fetch_url


async def test_bilibili_b23_with_bv_in_path_needs_no_network() -> None:
    source = BilibiliSource(settings(), transport=no_network_transport())
    ref = await source.resolve(f"https://b23.tv/{BV}")
    assert ref.canonical_id == f"{BV}-p1"


async def test_bilibili_resolve_rejects_non_video_url() -> None:
    source = BilibiliSource(settings(), transport=no_network_transport())
    with pytest.raises(errors.UnsupportedUrlError):
        await source.resolve("https://www.bilibili.com/read/cv12345")


def test_bilibili_matches() -> None:
    source = BilibiliSource(settings())
    assert source.matches(f"https://www.bilibili.com/video/{BV}")
    assert source.matches("https://b23.tv/abc123")
    assert not source.matches("https://www.bilibili.com/read/cv12345")
    assert not source.matches("https://example.com/video/BV1xx411c7mD")
    assert not source.matches("garbage")


# ── bilibili fetch (yt-dlp mocked via the downloader seam) ───────────────────


def fake_info(dest_dir: Path) -> dict[str, Any]:
    video = dest_dir / f"{BV}.mp4"
    video.write_bytes(b"fake")
    return {
        "id": BV,
        "title": "红烧肉教程",
        "uploader": "某厨师",
        "duration": 312.6,
        "webpage_url": f"https://www.bilibili.com/video/{BV}/",
        "format": "480p",
        "height": 480,
        "ext": "mp4",
        "requested_downloads": [{"filepath": str(video)}],
    }


async def test_bilibili_fetch_anonymous_by_default(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def downloader(url: str, opts: dict[str, Any]) -> dict[str, Any]:
        seen["url"] = url
        seen["opts"] = opts
        return fake_info(tmp_path)

    source = BilibiliSource(settings(), downloader=downloader)
    ref = CanonicalRef("bilibili", f"{BV}-p1", f"https://www.bilibili.com/video/{BV}/?p=1")
    media = await source.fetch(ref, tmp_path)

    assert seen["url"] == ref.fetch_url
    assert "http_headers" not in seen["opts"]  # anonymous-first: no cookie header
    assert "proxy" not in seen["opts"]  # direct by default — no fetch proxy
    assert seen["opts"]["format_sort"] == ["res:480"]  # capped ≤480p
    assert seen["opts"]["noplaylist"] is True
    assert media.video_path == tmp_path / f"{BV}.mp4"
    assert media.title == "红烧肉教程"
    assert media.creator == "某厨师"
    assert media.duration_seconds == 313


async def test_bilibili_fetch_sends_cookie_only_when_configured(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def downloader(url: str, opts: dict[str, Any]) -> dict[str, Any]:
        seen["opts"] = opts
        return fake_info(tmp_path)

    cookie = "SESSDATA=" + "x" * 20  # fake, assembled — never a real credential
    source = BilibiliSource(settings(bilibili_cookie=cookie), downloader=downloader)
    ref = CanonicalRef("bilibili", f"{BV}-p1", f"https://www.bilibili.com/video/{BV}/?p=1")
    await source.fetch(ref, tmp_path)
    assert seen["opts"]["http_headers"]["Cookie"] == cookie


async def test_bilibili_fetch_proxy_passed_to_yt_dlp_when_set(tmp_path: Path) -> None:
    """M-Deploy fetch-proxy knob: yt-dlp gets the proxy as an opt when set."""
    seen: dict[str, Any] = {}

    def downloader(url: str, opts: dict[str, Any]) -> dict[str, Any]:
        seen["opts"] = opts
        return fake_info(tmp_path)

    source = BilibiliSource(settings(chefclaw_fetch_proxy=PROXY), downloader=downloader)
    ref = CanonicalRef("bilibili", f"{BV}-p1", f"https://www.bilibili.com/video/{BV}/?p=1")
    await source.fetch(ref, tmp_path)
    assert seen["opts"]["proxy"] == PROXY


async def test_bilibili_short_link_resolution_uses_fetch_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """b23.tv resolution is platform-fetch traffic — the knob covers it too."""
    calls = spy_async_client("chefclaw.sources.bilibili", monkeypatch)
    target = f"https://www.bilibili.com/video/{BV}?p=2"
    source = BilibiliSource(
        settings(chefclaw_fetch_proxy=PROXY), transport=redirect_transport(target)
    )
    ref = await source.resolve("https://b23.tv/abc123")
    assert ref.canonical_id == f"{BV}-p2"
    assert calls[0]["proxy"] == PROXY


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("HTTP Error 412: Precondition Failed", errors.RateLimitedError),
        ("HTTP Error 429: Too Many Requests", errors.RateLimitedError),
        ("Unable to download webpage: timed out", errors.DownloadFailedError),
        ("This video is unavailable", errors.DownloadFailedError),
    ],
)
async def test_bilibili_fetch_error_mapping(
    tmp_path: Path, message: str, expected: type[errors.ChefclawError]
) -> None:
    def downloader(url: str, opts: dict[str, Any]) -> dict[str, Any]:
        raise Exception(message)  # yt-dlp's DownloadError is message-shaped

    source = BilibiliSource(settings(), downloader=downloader)
    ref = CanonicalRef("bilibili", f"{BV}-p1", f"https://www.bilibili.com/video/{BV}/?p=1")
    with pytest.raises(expected):
        await source.fetch(ref, tmp_path)


async def test_bilibili_fetch_taxonomy_errors_pass_through_unwrapped(tmp_path: Path) -> None:
    """A typed error raised inside the downloader must NOT be re-wrapped as
    DownloadFailedError — the taxonomy mapping is for foreign exceptions only."""

    def downloader(url: str, opts: dict[str, Any]) -> dict[str, Any]:
        raise errors.ConfigError("ffmpeg missing from the image")

    source = BilibiliSource(settings(), downloader=downloader)
    ref = CanonicalRef("bilibili", f"{BV}-p1", f"https://www.bilibili.com/video/{BV}/?p=1")
    with pytest.raises(errors.ConfigError):
        await source.fetch(ref, tmp_path)


async def test_bilibili_fetch_video_path_fallback_from_template(tmp_path: Path) -> None:
    """No requested_downloads in the info dict: fall back to {id}.{ext} on disk.
    Absent duration stays None (Hard Rule 7 discipline for metadata)."""

    def downloader(url: str, opts: dict[str, Any]) -> dict[str, Any]:
        (tmp_path / f"{BV}.mp4").write_bytes(b"fake")
        return {"id": BV, "ext": "mp4", "title": "红烧肉"}

    source = BilibiliSource(settings(), downloader=downloader)
    ref = CanonicalRef("bilibili", f"{BV}-p1", f"https://www.bilibili.com/video/{BV}/?p=1")
    media = await source.fetch(ref, tmp_path)
    assert media.video_path == tmp_path / f"{BV}.mp4"
    assert media.duration_seconds is None
    assert media.creator is None


async def test_bilibili_fetch_no_output_file_is_typed_failure(tmp_path: Path) -> None:
    def downloader(url: str, opts: dict[str, Any]) -> dict[str, Any]:
        return {"id": BV, "ext": "mp4"}  # claims success, wrote nothing

    source = BilibiliSource(settings(), downloader=downloader)
    ref = CanonicalRef("bilibili", f"{BV}-p1", f"https://www.bilibili.com/video/{BV}/?p=1")
    with pytest.raises(errors.DownloadFailedError):
        await source.fetch(ref, tmp_path)


# ── rednote canonical ids (§16.1: identity is the note id, token-free;
#    fetch_url KEEPS xsec_token — spike-verified that XHS rejects bare ids) ──

CLEAN_FETCH_URL = f"https://www.xiaohongshu.com/explore/{NOTE_ID}"


@pytest.mark.parametrize(
    ("url", "fetch_url"),
    [
        (f"https://www.xiaohongshu.com/explore/{NOTE_ID}", CLEAN_FETCH_URL),
        # xsec_token survives into fetch_url (required by XHS); every other
        # share param is dropped; identity stays the bare note id.
        (
            f"https://www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token=ABtok-en_0=&xsec_source=pc_share",
            f"{CLEAN_FETCH_URL}?xsec_token=ABtok-en_0=",
        ),
        (f"https://www.xiaohongshu.com/discovery/item/{NOTE_ID}", CLEAN_FETCH_URL),
        (
            f"https://xiaohongshu.com/discovery/item/{NOTE_ID}?app_platform=ios&share_from=weixin",
            CLEAN_FETCH_URL,
        ),
    ],
)
async def test_rednote_canonical_id(url: str, fetch_url: str) -> None:
    source = RednoteSource(settings(), transport=no_network_transport())
    ref = await source.resolve(url)
    assert ref == CanonicalRef(platform="rednote", canonical_id=NOTE_ID, fetch_url=fetch_url)


async def test_rednote_xhslink_short_link_follows_redirect() -> None:
    target = f"https://www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token=ABshareToken&xsec_source=share"
    source = RednoteSource(settings(), transport=redirect_transport(target))
    ref = await source.resolve("https://xhslink.com/a/AbCdEf123")
    assert ref.canonical_id == NOTE_ID  # identity is token-free either way
    assert ref.fetch_url == f"{CLEAN_FETCH_URL}?xsec_token=ABshareToken"


async def test_rednote_resolve_rejects_non_note_url() -> None:
    source = RednoteSource(settings(), transport=no_network_transport())
    with pytest.raises(errors.UnsupportedUrlError):
        await source.resolve("https://www.xiaohongshu.com/explore/nothexid")


def test_rednote_matches() -> None:
    source = RednoteSource(settings())
    assert source.matches(f"https://www.xiaohongshu.com/explore/{NOTE_ID}")
    assert source.matches(f"https://www.xiaohongshu.com/discovery/item/{NOTE_ID}")
    assert source.matches("https://xhslink.com/a/AbCdEf123")
    assert not source.matches("https://www.xiaohongshu.com/user/profile/abc")
    assert not source.matches("garbage")


# ── rednote fetch (sidecar mocked; guest tier is the default — §16.10) ───────


def sidecar_transport(
    captured: dict[str, Any],
    *,
    detail_response: httpx.Response | None = None,
    media_bytes: bytes = b"media-bytes",
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/xhs/detail":
            captured["detail_json"] = json.loads(request.content)
            if detail_response is not None:
                return detail_response
            return httpx.Response(
                200,
                json={
                    "message": "获取数据成功",
                    "data": {
                        "作品标题": "家常红烧肉",
                        "作者昵称": "小厨娘",
                        "作品类型": "视频",
                        "时长": "05:20",
                        "下载地址": ["https://cdn.example.com/stream/video.mp4"],
                    },
                },
            )
        if request.url.host == "cdn.example.com":
            captured["media_headers"] = dict(request.headers)
            return httpx.Response(200, content=media_bytes)
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def rednote_ref() -> CanonicalRef:
    return CanonicalRef("rednote", NOTE_ID, f"https://www.xiaohongshu.com/explore/{NOTE_ID}")


async def test_rednote_fetch_requires_sidecar_url(tmp_path: Path) -> None:
    source = RednoteSource(settings(xhs_sidecar_url=""))
    with pytest.raises(errors.ConfigError):
        await source.fetch(rednote_ref(), tmp_path)


async def test_rednote_fetch_guest_mode_sends_no_cookie(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    source = RednoteSource(
        settings(xhs_sidecar_url="http://xhs:5556"),
        transport=sidecar_transport(captured),
    )
    media = await source.fetch(rednote_ref(), tmp_path)

    assert captured["detail_json"] == {
        "url": f"https://www.xiaohongshu.com/explore/{NOTE_ID}",
        "download": False,
    }  # guest tier: NO cookie key at all
    assert media.video_path.read_bytes() == b"media-bytes"
    assert media.video_path.parent == tmp_path
    assert media.title == "家常红烧肉"
    assert media.creator == "小厨娘"
    assert media.duration_seconds == 320


async def test_rednote_fetch_cookie_mode_sends_cookie_and_ua(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    cookie = "web_session=" + "0" * 20  # fake, assembled — never a real credential
    source = RednoteSource(
        settings(
            xhs_sidecar_url="http://xhs:5556",
            xhs_cookie=cookie,
            xhs_user_agent="Mozilla/5.0 (test)",
        ),
        transport=sidecar_transport(captured),
    )
    await source.fetch(rednote_ref(), tmp_path)
    assert captured["detail_json"]["cookie"] == cookie
    assert captured["media_headers"]["user-agent"] == "Mozilla/5.0 (test)"


async def test_rednote_fetch_proxy_routes_platform_traffic_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-Deploy fetch-proxy knob (ladder rungs b/c/d): the sidecar payload
    carries the proxy for the sidecar's own platform call, and the api's
    media-download client is constructed with it — but the api→sidecar client
    stays DIRECT (that hop is compose-internal by design)."""
    calls = spy_async_client("chefclaw.sources.rednote", monkeypatch)
    captured: dict[str, Any] = {}
    source = RednoteSource(
        settings(xhs_sidecar_url="http://xhs:5556", chefclaw_fetch_proxy=PROXY),
        transport=sidecar_transport(captured),
    )
    media = await source.fetch(rednote_ref(), tmp_path)

    assert captured["detail_json"] == {
        "url": f"https://www.xiaohongshu.com/explore/{NOTE_ID}",
        "download": False,
        "proxy": PROXY,
    }
    # fetch() constructs exactly two clients: [0] api→sidecar (direct),
    # [1] media download (proxied).
    assert len(calls) == 2
    assert "proxy" not in calls[0]
    assert calls[1]["proxy"] == PROXY
    assert media.video_path.read_bytes() == b"media-bytes"


async def test_rednote_fetch_without_proxy_builds_direct_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Knob unset (the default): no `proxy` kwarg on any client, no `proxy`
    key in the sidecar payload — everything direct."""
    calls = spy_async_client("chefclaw.sources.rednote", monkeypatch)
    captured: dict[str, Any] = {}
    source = RednoteSource(
        settings(xhs_sidecar_url="http://xhs:5556"),
        transport=sidecar_transport(captured),
    )
    await source.fetch(rednote_ref(), tmp_path)
    assert "proxy" not in captured["detail_json"]
    assert all("proxy" not in kwargs for kwargs in calls)


async def test_rednote_short_link_resolution_uses_fetch_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """xhslink.com resolution is platform-fetch traffic — the knob covers it."""
    calls = spy_async_client("chefclaw.sources.rednote", monkeypatch)
    target = f"https://www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token=ABshareToken"
    source = RednoteSource(
        settings(chefclaw_fetch_proxy=PROXY), transport=redirect_transport(target)
    )
    ref = await source.resolve("https://xhslink.com/a/AbCdEf123")
    assert ref.canonical_id == NOTE_ID
    assert calls[0]["proxy"] == PROXY


@pytest.mark.parametrize(
    ("detail_response", "expected"),
    [
        (
            httpx.Response(200, json={"message": "Cookie 已失效，请重新登录", "data": None}),
            errors.CookiesExpiredError,
        ),
        (
            httpx.Response(200, json={"message": "请求过于频繁", "data": None}),
            errors.RateLimitedError,
        ),
        (httpx.Response(429, json={"message": "throttled"}), errors.RateLimitedError),
        (
            httpx.Response(200, json={"message": "获取数据失败", "data": None}),
            errors.DownloadFailedError,
        ),
        (httpx.Response(500, text="boom"), errors.DownloadFailedError),
        (
            httpx.Response(200, json={"message": "ok", "data": {"下载地址": []}}),
            errors.DownloadFailedError,
        ),
    ],
)
async def test_rednote_fetch_error_mapping(
    tmp_path: Path, detail_response: httpx.Response, expected: type[errors.ChefclawError]
) -> None:
    source = RednoteSource(
        settings(xhs_sidecar_url="http://xhs:5556"),
        transport=sidecar_transport({}, detail_response=detail_response),
    )
    with pytest.raises(expected):
        await source.fetch(rednote_ref(), tmp_path)


@pytest.mark.parametrize(
    "detail_response",
    [
        # Valid JSON but not an object — must map to the taxonomy, never
        # escape as an AttributeError.
        httpx.Response(200, json=["not", "an", "object"]),
        # `data` present and truthy but not an object.
        httpx.Response(200, json={"message": "ok", "data": "not-an-object"}),
    ],
)
async def test_rednote_fetch_malformed_sidecar_payload(
    tmp_path: Path, detail_response: httpx.Response
) -> None:
    source = RednoteSource(
        settings(xhs_sidecar_url="http://xhs:5556"),
        transport=sidecar_transport({}, detail_response=detail_response),
    )
    with pytest.raises(errors.DownloadFailedError):
        await source.fetch(rednote_ref(), tmp_path)


async def test_rednote_fetch_missing_duration_stays_none(tmp_path: Path) -> None:
    """Hard Rule 7 discipline for metadata: absent upstream ⇒ None, never guessed."""
    detail_response = httpx.Response(
        200,
        json={
            "message": "ok",
            "data": {
                "作品标题": "无时长字段的视频",
                "作者昵称": "up主",
                "下载地址": ["https://cdn.example.com/stream/video.mp4"],
            },
        },
    )
    source = RednoteSource(
        settings(xhs_sidecar_url="http://xhs:5556"),
        transport=sidecar_transport({}, detail_response=detail_response),
    )
    media = await source.fetch(rednote_ref(), tmp_path)
    assert media.duration_seconds is None
    assert media.title == "无时长字段的视频"


async def test_rednote_fetch_image_note_downloads_all_media(tmp_path: Path) -> None:
    detail_response = httpx.Response(
        200,
        json={
            "message": "ok",
            "data": {
                "作品标题": "图文菜谱",
                "作品类型": "图文",
                "下载地址": [
                    "https://cdn.example.com/img/1.jpg",
                    "https://cdn.example.com/img/2.png",
                ],
            },
        },
    )
    source = RednoteSource(
        settings(xhs_sidecar_url="http://xhs:5556"),
        transport=sidecar_transport({}, detail_response=detail_response),
    )
    media = await source.fetch(rednote_ref(), tmp_path)
    expected = [tmp_path / f"{NOTE_ID}-0.jpg", tmp_path / f"{NOTE_ID}-1.png"]
    assert media.video_path == expected[0]
    assert [Path(p) for p in media.extra["media_paths"]] == expected
    assert all(p.read_bytes() == b"media-bytes" for p in expected)


async def test_rednote_guest_login_required_message_names_the_tier(tmp_path: Path) -> None:
    """§16.10: in guest mode a login-required failure must not claim a session
    existed — it directs to the tier-1 throwaway, never the main account."""
    detail_response = httpx.Response(200, json={"message": "需要登录后才能查看", "data": None})
    source = RednoteSource(
        settings(xhs_sidecar_url="http://xhs:5556"),  # guest: no cookie configured
        transport=sidecar_transport({}, detail_response=detail_response),
    )
    with pytest.raises(errors.CookiesExpiredError, match="guest tier"):
        await source.fetch(rednote_ref(), tmp_path)


async def test_rednote_fetch_sidecar_unreachable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    source = RednoteSource(
        settings(xhs_sidecar_url="http://xhs:5556"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(errors.DownloadFailedError):
        await source.fetch(rednote_ref(), tmp_path)


# ── local file (§16.10 tier 2: content-addressed dedupe) ─────────────────────


async def test_localfile_ingest_content_addressed(tmp_path: Path) -> None:
    content = b"the same video bytes"
    expected_id = f"file-{hashlib.sha256(content).hexdigest()[:16]}"
    upload = tmp_path / "upload" / "saved_from_phone.mp4"
    upload.parent.mkdir()
    upload.write_bytes(content)
    dest = tmp_path / "media"

    source = LocalFileSource(dest)
    ref, media = await source.ingest(upload, "https://example.com/original", "rednote")

    assert ref == CanonicalRef("local", expected_id, "https://example.com/original")
    assert media.video_path == dest / f"{expected_id}.mp4"
    assert media.video_path.read_bytes() == content
    assert media.title is None and media.creator is None  # never fabricated
    assert media.duration_seconds is None
    assert media.extra["sha256"] == hashlib.sha256(content).hexdigest()
    assert media.extra["platform_hint"] == "rednote"
    assert media.extra["original_filename"] == "saved_from_phone.mp4"

    # Re-uploading the same bytes under another name dedupes to the same id.
    upload2 = tmp_path / "upload" / "different_name.mp4"
    upload2.write_bytes(content)
    ref2, media2 = await source.ingest(upload2, None, None)
    assert ref2.canonical_id == expected_id
    assert ref2.fetch_url == f"local://{expected_id}"
    assert media2.video_path == media.video_path


async def test_localfile_ingest_missing_file(tmp_path: Path) -> None:
    source = LocalFileSource(tmp_path)
    with pytest.raises(errors.DownloadFailedError):
        await source.ingest(tmp_path / "nope.mp4", None, None)


# ── fake source (worker tests + golden suite depend on it) ───────────────────


async def test_fake_source_happy_path(tmp_path: Path) -> None:
    fake = FakeSource(canonical_id="fake-abc")
    url = "fake://video/1"
    assert fake.matches(url)
    ref = await fake.resolve(url)
    assert ref == CanonicalRef("fake", "fake-abc", url)
    media = await fake.fetch(ref, tmp_path)
    assert media.video_path.exists()
    assert fake.resolve_calls == [url]
    assert fake.fetch_calls == [ref]


async def test_fake_source_failure_injection(tmp_path: Path) -> None:
    fake = FakeSource().fail_fetch(errors.RateLimitedError("throttled"), times=2)
    ref = await fake.resolve("fake://video/2")
    for _ in range(2):
        with pytest.raises(errors.RateLimitedError):
            await fake.fetch(ref, tmp_path)
    media = await fake.fetch(ref, tmp_path)  # injected failures exhausted
    assert media.video_path.exists()

    fake_resolve = FakeSource().fail_resolve(errors.UnsupportedUrlError)  # class form, forever
    for _ in range(2):
        with pytest.raises(errors.UnsupportedUrlError):
            await fake_resolve.resolve("fake://video/3")
