"""SSRF guard: refuse to fetch a URL whose host resolves to a non-public address.

Applied to the one fetch target in this codebase that is NOT platform-allowlisted:
the Rednote CDN media URLs the (unauthenticated, internal) XHS sidecar returns
from parsing attacker-influenced note content (V2-D audit finding). A crafted note
could name an internal target — cloud metadata (169.254.169.254), a compose-internal
host, 127.0.0.1 — which the api would otherwise stream to disk. Resolving the host
and rejecting private/loopback/link-local/reserved ranges BEFORE the fetch closes
the direct SSRF vector.

Paste URLs never reach here: each adapter's ``matches()`` gates them by an explicit
per-platform host allowlist (bilibili.com / xiaohongshu.com), so an arbitrary URL is
rejected at enqueue. This guard is the belt for the one URL that arrives from the
sidecar rather than from the user's paste.

Residuals (documented, V2-D ADR): (1) DNS-rebinding — the host is resolved here and
again by httpx, so a name that flips between the two lookups isn't caught; not a
concern for the static-internal-URL threat this closes. (2) The redirect CHAIN of a
followed request re-checks only the initial host, not each hop.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeFetchTargetError(Exception):
    """A fetch target resolved to a non-public address (SSRF guard tripped)."""


def _is_public_ip(raw_ip: str) -> bool:
    """True only for a globally-routable unicast address. Everything else
    (RFC-1918 private, loopback, link-local incl. 169.254.169.254 cloud
    metadata, ULA, reserved, multicast, unspecified) is refused."""
    addr = ipaddress.ip_address(raw_ip)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_public_url(url: str, *, resolver=socket.getaddrinfo) -> None:
    """Raise ``UnsafeFetchTargetError`` unless ``url`` is http(s) and its host
    resolves to ONLY public addresses. ``resolver`` is a seam (socket.getaddrinfo
    by default) so tests validate the logic without real DNS. Blocking DNS — call
    it off the event loop (``asyncio.to_thread``) in async fetch paths."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeFetchTargetError(f"refusing non-http(s) fetch target: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeFetchTargetError("refusing fetch target with no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = resolver(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeFetchTargetError(f"cannot resolve fetch host {host!r}: {exc}") from exc
    for info in infos:
        ip = info[4][0]
        if not _is_public_ip(ip):
            raise UnsafeFetchTargetError(
                f"fetch host {host!r} resolves to non-public address {ip} — refusing"
            )
