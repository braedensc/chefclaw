"""Admin invite routes + the public invite-accept lookup (M2 PR 3).

Every ``/api/admin/*`` route depends on ``require_admin`` (critique M9 — the
frontend ``me.is_admin`` gate is cosmetic; a non-admin hitting these directly is
a 403 from the dependency). ``GET /api/invites/{token}`` is PUBLIC (the invite-
accept page reads it) and returns a uniform shape that never leaks a revoked/
expired address (M13).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from chefclaw import db
from chefclaw.auth import require_admin
from chefclaw.config import Settings, get_settings
from chefclaw.emailer import get_email_adapter
from chefclaw.errors import ConfigError, EmailSendError
from chefclaw.routers.deps import error_response
from chefclaw.schemas import ErrorBody, InviteCreate, InviteList, InviteOut, InvitePublicOut
from chefclaw.services import invites

router = APIRouter(prefix="/api", tags=["invites"])

_ERR = {"model": ErrorBody}


def _activation_link(settings: Settings, raw_token: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/invite/{raw_token}"


def _invite_out(row: invites.InviteRow, *, activation_link: str | None = None) -> InviteOut:
    return InviteOut(
        id=row.id,
        email=row.email,
        status=row.status,
        expires_at=row.expires_at,
        created_at=row.created_at,
        accepted_at=row.accepted_at,
        dev_activation_link=activation_link,
    )


@router.post(
    "/admin/invites",
    response_model=InviteOut,
    status_code=201,
    responses={200: {"model": InviteOut}, 409: _ERR, 502: _ERR, 503: _ERR},
)
async def create_invite(
    body: InviteCreate,
    owner_id: Annotated[uuid.UUID, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> InviteOut | JSONResponse:
    """Issue (or rotate + resend) a pending invite. Already an active member ⇒
    409; a new invite ⇒ 201; a rotate/resend ⇒ 200. The activation link is
    emailed; it rides in the response ONLY when chefclaw_email='fake'."""
    if not settings.public_base_url.strip():
        # An invite email with a localhost link is useless — fail closed (503).
        return error_response(
            503, "config_error", "PUBLIC_BASE_URL is unset — cannot build an invite link."
        )
    sm = db.get_sessionmaker()
    if await invites.active_member_exists(sm, body.email):
        return error_response(409, "already_member", "that email is already an active member")

    row, raw, is_new = await invites.issue_invite(
        sm, settings, invited_by=owner_id, email=body.email
    )
    link = _activation_link(settings, raw)
    try:
        email_adapter = get_email_adapter(settings)  # ConfigError (ses w/o creds) ⇒ 503
        await email_adapter.send_invite(to_email=row.email, activation_link=link)
    except ConfigError as exc:
        return error_response(503, exc.error_type, str(exc))
    except EmailSendError as exc:
        return error_response(502, exc.error_type, str(exc))

    if not is_new:
        response.status_code = 200
    dev_link = link if settings.chefclaw_email == "fake" else None
    return _invite_out(row, activation_link=dev_link)


@router.get("/admin/invites", response_model=InviteList)
async def list_invites(
    owner_id: Annotated[uuid.UUID, Depends(require_admin)],
    status: str | None = None,
) -> InviteList:
    """List invites (newest first), optionally filtered by status. NEVER returns
    a token_hash."""
    rows = await invites.list_invites(db.get_sessionmaker(), status=status)
    return InviteList(items=[_invite_out(r) for r in rows])


@router.post("/admin/invites/{invite_id}/revoke", responses={404: _ERR, 409: _ERR})
async def revoke_invite(
    invite_id: uuid.UUID,
    owner_id: Annotated[uuid.UUID, Depends(require_admin)],
) -> Response:
    """Revoke a pending invite (idempotent). Already-accepted ⇒ 409; missing ⇒
    404; otherwise 200."""
    outcome = await invites.revoke_invite(db.get_sessionmaker(), invite_id)
    if outcome == "not_found":
        return error_response(404, "not_found", f"no invite {invite_id}")
    if outcome == "already_accepted":
        return error_response(409, "already_accepted", "an accepted invite cannot be revoked")
    return JSONResponse(status_code=200, content={"status": "revoked"})


@router.get("/invites/{token}", response_model=InvitePublicOut)
async def public_invite(token: str) -> InvitePublicOut:
    """PUBLIC invite-accept lookup (M13): a live pending invite reveals its
    email; a missing/expired/revoked/accepted token is a uniform 'invalid' with
    no email (no enumeration oracle, no address leak)."""
    result = await invites.public_invite(db.get_sessionmaker(), token)
    return InvitePublicOut(status=result.status, email=result.email)
