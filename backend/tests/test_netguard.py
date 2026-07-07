"""SSRF guard (chefclaw.netguard) — unit tier, no real network.

The ``resolver`` seam lets these assert the private/loopback/link-local logic
without DNS; the literal-IP cases resolve locally via getaddrinfo (still no
network). This is the guard behind the Rednote media-download SSRF finding (V2-D).
"""

import socket

import pytest

from chefclaw.netguard import UnsafeFetchTargetError, assert_public_url


def _resolver_for(*ips: str):
    """A fake getaddrinfo returning the given IP(s) for any host."""

    def resolver(host, port, type=None):  # noqa: A002 - mirrors socket.getaddrinfo
        out = []
        for ip in ips:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            out.append((family, socket.SOCK_STREAM, 6, "", (ip, port)))
        return out

    return resolver


def test_public_ipv4_passes() -> None:
    # Returns None (no raise) for a globally-routable address.
    resolver = _resolver_for("93.184.216.34")
    assert assert_public_url("https://cdn.example.com/v.mp4", resolver=resolver) is None


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC-1918
        "192.168.1.1",  # RFC-1918
        "172.16.0.1",  # RFC-1918
        "169.254.169.254",  # link-local — cloud metadata
        "0.0.0.0",  # unspecified
        "::1",  # IPv6 loopback
        "fc00::1",  # IPv6 ULA (private)
        "fe80::1",  # IPv6 link-local
    ],
)
def test_non_public_ip_rejected(ip: str) -> None:
    with pytest.raises(UnsafeFetchTargetError):
        assert_public_url("https://evil.example/x", resolver=_resolver_for(ip))


def test_any_private_address_among_public_rejects() -> None:
    """A host resolving to both a public AND a private address is refused (a
    rebinding-style host must not slip through on its public record)."""
    with pytest.raises(UnsafeFetchTargetError):
        assert_public_url(
            "https://sneaky.example/x", resolver=_resolver_for("93.184.216.34", "127.0.0.1")
        )


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://host/x", "gopher://host/", "//host/x", "data:text/plain,x"]
)
def test_non_http_scheme_rejected(url: str) -> None:
    with pytest.raises(UnsafeFetchTargetError):
        assert_public_url(url)


def test_literal_loopback_host_rejected_without_network() -> None:
    # A literal IP host resolves locally (no DNS), so the default resolver is fine.
    with pytest.raises(UnsafeFetchTargetError):
        assert_public_url("http://127.0.0.1:8080/x")


def test_unresolvable_host_rejected() -> None:
    def resolver(host, port, type=None):  # noqa: A002
        raise socket.gaierror("no such host")

    with pytest.raises(UnsafeFetchTargetError):
        assert_public_url("https://nx.invalid/x", resolver=resolver)


def test_missing_host_rejected() -> None:
    with pytest.raises(UnsafeFetchTargetError):
        assert_public_url("https:///no-host")
