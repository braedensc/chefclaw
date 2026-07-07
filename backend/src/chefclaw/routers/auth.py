"""Auth routes (M2, ADR 2026-07-07-m2-accounts-and-invites).

Mounted BEFORE the SPA catch-all so ``/api/auth/*`` and ``/api/me`` win. The
login→callback flow persists state/PKCE/nonce in a short-lived, SINGLE-USE
HttpOnly ``oauth_tx`` cookie (critique M3); ``next`` is same-origin-only (M4);
the callback mints an opaque server-side session (cookie flags derived from env,
M8). In PR 2 only a RETURNING user (a bound OAuth identity) is admitted — first
activation (invite consume + bootstrap-claim) lands in PR 3; until then an
unbound identity gets ONE opaque 403 (fail closed, M6).
"""

import base64
import hmac
import json
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select

from chefclaw import auth, db, sessions
from chefclaw.config import Settings, get_settings
from chefclaw.errors import ConfigError
from chefclaw.models import User, UserStatus
from chefclaw.oauth import VerifiedIdentity, get_oauth_provider, pkce_pair
from chefclaw.schemas import MeOut

router = APIRouter(prefix="/api", tags=["auth"])

OAUTH_TX_COOKIE = "oauth_tx"
_OAUTH_TX_MAX_AGE = 300  # 5 min — the login→callback round trip (critique M3)
_OAUTH_TX_PATH = "/api/auth"
_SESSION_PATH = "/"


# ── helpers ──────────────────────────────────────────────────────────────────


def safe_next(raw: str | None) -> str:
    """Same-origin path only (critique M4): must start with a single '/', carry
    no scheme, no backslash, no control chars (header-injection defense), and
    not be protocol-relative ('//'). Anything else ⇒ '/', so a crafted
    ``?next=https://evil`` can never open-redirect off-site."""
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return "/"
    if "://" in raw or "\\" in raw or any(ord(c) < 0x20 for c in raw):
        return "/"
    return raw


def _encode_tx(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode("ascii")


def _decode_tx(raw: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(raw.encode()))


def _redirect_uri(settings: Settings, request: Request) -> str:
    """The OAuth redirect URI. Prod pins it to the Cloud-Console-registered
    GOOGLE_OAUTH_REDIRECT_URL (must match exactly); unset (fake/dev) derives it
    from the request so the loop-back callback works."""
    if settings.google_oauth_redirect_url:
        return settings.google_oauth_redirect_url
    return str(request.url_for("google_callback"))


def _set_tx_cookie(resp: Response, value: str, settings: Settings) -> None:
    resp.set_cookie(
        OAUTH_TX_COOKIE,
        value,
        max_age=_OAUTH_TX_MAX_AGE,
        path=_OAUTH_TX_PATH,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


def _clear_tx_cookie(resp: Response) -> None:
    resp.delete_cookie(OAUTH_TX_COOKIE, path=_OAUTH_TX_PATH)


def _set_session_cookie(resp: Response, raw_token: str, settings: Settings) -> None:
    resp.set_cookie(
        auth.SESSION_COOKIE_NAME,
        raw_token,
        max_age=settings.session_ttl_hours * 3600,
        path=_SESSION_PATH,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


def _bad_request(detail: str) -> JSONResponse:
    """A malformed sign-in request (missing/invalid tx or state). Clears the
    single-use tx cookie. Distinct from the opaque 403 (which is about WHO may
    sign in — this is about a broken request)."""
    resp = JSONResponse(status_code=400, content={"error_type": "bad_request", "detail": detail})
    _clear_tx_cookie(resp)
    return resp


def _opaque_denied() -> JSONResponse:
    """ONE opaque 403 for EVERY callback rejection (critique M6): no users row,
    no session, and no 'no invite' vs 'email mismatch' vs 'unverified' oracle.
    Clears the single-use tx cookie."""
    resp = JSONResponse(
        status_code=403,
        content={
            "error_type": "sign_in_denied",
            "detail": "Sign-in is not permitted for this account.",
        },
    )
    _clear_tx_cookie(resp)
    return resp


async def resolve_owner_by_identity(identity: VerifiedIdentity) -> uuid.UUID | None:
    """A RETURNING user bound to this (oauth_provider, oauth_subject) and still
    active. First activation (invite consume / bootstrap-claim) is PR 3 — until
    then an unbound identity resolves to None (→ opaque 403). Stubbable."""
    async with db.get_sessionmaker()() as session:
        row = (
            await session.execute(
                select(User.id).where(
                    User.oauth_provider == identity.provider,
                    User.oauth_subject == identity.subject,
                    User.status == UserStatus.ACTIVE.value,
                )
            )
        ).first()
    return row[0] if row else None


# ── routes ───────────────────────────────────────────────────────────────────


@router.get("/auth/google/login")
async def google_login(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    next: str = "/",
) -> RedirectResponse:
    """Mint state + PKCE + nonce, stash them in the 5-min single-use oauth_tx
    cookie, and 302 to Google (or the fake provider's loop-back)."""
    provider = get_oauth_provider(settings)  # ConfigError (google w/o creds) ⇒ 500 misconfig
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    auth_url = provider.authorization_url(
        redirect_uri=_redirect_uri(settings, request),
        state=state,
        nonce=nonce,
        code_challenge=challenge,
    )
    resp = RedirectResponse(auth_url, status_code=302)
    _set_tx_cookie(
        resp,
        _encode_tx(
            {"state": state, "nonce": nonce, "verifier": verifier, "next": safe_next(next)}
        ),
        settings,
    )
    return resp


@router.get("/auth/google/callback", name="google_callback")
async def google_callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    code: str = "",
    state: str = "",
) -> Response:
    """Verify state + the ID token, gate the identity, mint a session. The
    oauth_tx cookie is read ONCE and cleared on every response (single-use, M3)."""
    raw_tx = request.cookies.get(OAUTH_TX_COOKIE)
    if not raw_tx:  # M3: reject if absent
        return _bad_request("missing or expired sign-in transaction")
    try:
        tx = _decode_tx(raw_tx)
        expected_state = tx["state"]
        nonce = tx["nonce"]
        verifier = tx["verifier"]
        next_path = safe_next(tx["next"])
    except Exception:
        return _bad_request("invalid sign-in transaction")
    # State (CSRF) — constant-time compare against the stashed value (M3).
    if not code or not state or not hmac.compare_digest(state, expected_state):
        return _bad_request("invalid sign-in state")

    provider = get_oauth_provider(settings)
    try:
        identity = await provider.fetch_identity(
            code=code,
            code_verifier=verifier,
            redirect_uri=_redirect_uri(settings, request),
            expected_nonce=nonce,
        )
    except ConfigError:
        # Token exchange / ID-token verification failed — opaque (no oracle).
        return _opaque_denied()
    # M5: a verified email is required before any account match.
    if not identity.email_verified:
        return _opaque_denied()

    owner_id = await resolve_owner_by_identity(identity)
    if owner_id is None:
        # PR 3 wires invite-consume + the bootstrap_admin_email-gated claim here.
        return _opaque_denied()

    raw_session = await sessions.create_session(
        db.get_sessionmaker(), owner_id, ttl_hours=settings.session_ttl_hours
    )
    resp = RedirectResponse(next_path, status_code=302)
    _clear_tx_cookie(resp)  # single-use (M3)
    _set_session_cookie(resp, raw_session, settings)
    return resp


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    owner_id: Annotated[uuid.UUID, Depends(auth.require_owner)],
) -> Response:
    """Kill the session SERVER-SIDE (row DELETE — instant revocation) and clear
    the cookie. 204 either way (idempotent)."""
    raw = request.cookies.get(auth.SESSION_COOKIE_NAME)
    if raw:
        await sessions.delete_session(db.get_sessionmaker(), sessions.hash_token(raw))
    resp = Response(status_code=204)
    resp.delete_cookie(auth.SESSION_COOKIE_NAME, path=_SESSION_PATH)
    return resp


@router.get("/me", response_model=MeOut)
async def me(
    owner_id: Annotated[uuid.UUID, Depends(auth.require_owner)],
) -> MeOut | JSONResponse:
    """The authenticated identity (401 if unauthenticated — handled by
    require_owner). ``is_admin`` gates admin-UI visibility only; it is
    server-derived, never a writable field (critique M9)."""
    account = await auth.fetch_account(owner_id)
    if account is None:
        return JSONResponse(
            status_code=404,
            content={"error_type": "not_found", "detail": "no account for this session"},
        )
    return MeOut(
        id=account.id, name=account.name, email=account.email, is_admin=account.is_admin
    )
