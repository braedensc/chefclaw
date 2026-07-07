"""OAuth provider seam (M2, ADR 2026-07-07-m2-accounts-and-invites).

Server-side Google Authorization-Code + PKCE, mirroring the extractor seam:
config-selected and fail-closed. ``fake`` (default) returns a canned VERIFIED
identity without any network — it bypasses ONLY Google's network call, never the
invite/bootstrap gate downstream. ``google`` constructs the real provider (empty
creds ⇒ ConfigError). Unknown ⇒ ConfigError.

The provider does two things: build the authorization-redirect URL (with the
PKCE challenge + state + nonce the caller persists in the oauth_tx cookie), and
exchange the returned code for a VERIFIED identity (ID-token signature checked
against Google's JWKS, nonce matched). State/PKCE/nonce persistence + single-use
live in the auth router (critique M3); this module owns the provider crypto.

The Google path is UNVERIFIED-LIVE (a deploy human precondition, like the Gemini
extractor): CI exercises only the fake provider.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlencode

from chefclaw.errors import ConfigError

if TYPE_CHECKING:
    from chefclaw.config import Settings

__all__ = [
    "OAuthProvider",
    "VerifiedIdentity",
    "get_oauth_provider",
    "pkce_pair",
]

_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
_GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


@dataclass(frozen=True)
class VerifiedIdentity:
    """A VERIFIED OAuth identity. ``provider`` + ``subject`` is the stable
    binding for returning users; ``email`` (normalized downstream) is the
    invite-match key, gated on ``email_verified`` (critique M5)."""

    provider: str
    subject: str
    email: str
    email_verified: bool
    name: str | None


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    """A fresh (code_verifier, code_challenge) PKCE pair (S256). The verifier is
    persisted in the oauth_tx cookie and re-supplied at token exchange; the
    challenge goes to Google in the auth URL."""
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class OAuthProvider(Protocol):
    """What the auth router needs from an OAuth backend."""

    def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str: ...

    async def fetch_identity(
        self, *, code: str, code_verifier: str, redirect_uri: str, expected_nonce: str
    ) -> VerifiedIdentity: ...


class FakeOAuthProvider:
    """No-network stand-in (default). Returns a canned VERIFIED identity; the
    invite/bootstrap gate still runs for real downstream. Its authorization_url
    points straight back at the callback with a canned code so a test (or the
    golden suite) can drive login→callback end-to-end without Google."""

    # Canned identity — golden/unit tests seed a user with these to exercise the
    # returning-user session path, or (PR 3) an invite for this email.
    identity = VerifiedIdentity(
        provider="google",
        subject="fake-oauth-subject-1",
        email="fake-user@localhost",
        email_verified=True,
        name="Fake User",
    )

    def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        # Loop straight back to the callback (same-origin) so the flow is
        # drivable without a real consent screen. ``nonce``/``code_challenge``
        # are accepted and ignored (the fake doesn't mint a real ID token).
        return f"{redirect_uri}?{urlencode({'code': 'fake-auth-code', 'state': state})}"

    async def fetch_identity(
        self, *, code: str, code_verifier: str, redirect_uri: str, expected_nonce: str
    ) -> VerifiedIdentity:
        return self.identity


class GoogleOAuthProvider:
    """Real Google provider (Authorization-Code + PKCE). UNVERIFIED-LIVE — a
    deploy human precondition (Cloud Console client); CI never exercises it."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{_GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"

    async def fetch_identity(
        self, *, code: str, code_verifier: str, redirect_uri: str, expected_nonce: str
    ) -> VerifiedIdentity:
        # Lazy imports: the fake path never needs authlib/httpx-for-oauth.
        import httpx
        from authlib.jose import JsonWebKey, jwt

        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                _GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
            if token_resp.status_code != 200:
                raise ConfigError(
                    f"Google token exchange failed ({token_resp.status_code}) — "
                    "check the OAuth client id/secret and redirect URI."
                )
            id_token = token_resp.json().get("id_token")
            if not id_token:
                raise ConfigError("Google token response carried no id_token.")
            jwks = JsonWebKey.import_key_set((await client.get(_GOOGLE_JWKS_URI)).json())

        claims = jwt.decode(id_token, jwks)
        claims.validate()  # exp/iat/nbf
        if claims.get("iss") not in _GOOGLE_ISSUERS:
            raise ConfigError("Google ID token issuer mismatch.")
        if claims.get("aud") != self._client_id:
            raise ConfigError("Google ID token audience mismatch.")
        # Nonce binds the ID token to THIS login (critique M3) — a replayed token
        # from another flow carries a different nonce.
        if claims.get("nonce") != expected_nonce:
            raise ConfigError("Google ID token nonce mismatch.")
        return VerifiedIdentity(
            provider="google",
            subject=str(claims["sub"]),
            email=str(claims.get("email", "")),
            email_verified=bool(claims.get("email_verified", False)),
            name=claims.get("name"),
        )


def get_oauth_provider(settings: Settings) -> OAuthProvider:
    """Config-selected OAuth provider (``CHEFCLAW_AUTH_PROVIDER``), fail-closed.

    - ``fake`` (default) — canned verified identity, zero network, safe in CI.
    - ``google`` — the real provider; empty client id/secret ⇒ ConfigError
      (no half-configured OAuth, fail-closed like the extractor seam).
    - anything else — ConfigError (a typo must never silently pick a backend).
    """
    name = settings.chefclaw_auth_provider
    if name == "fake":
        return FakeOAuthProvider()
    if name == "google":
        if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
            raise ConfigError(
                "CHEFCLAW_AUTH_PROVIDER=google but GOOGLE_OAUTH_CLIENT_ID/SECRET is "
                "empty — no OAuth without explicit credentials (fail-closed)."
            )
        return GoogleOAuthProvider(
            settings.google_oauth_client_id, settings.google_oauth_client_secret
        )
    raise ConfigError(
        f"Unknown CHEFCLAW_AUTH_PROVIDER value {name!r} — expected 'fake' or 'google'."
    )
