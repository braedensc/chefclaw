"""Transactional email seam (M2 PR 3, ADR 2026-07-07-m2-accounts-and-invites).

Config-selected and fail-closed, mirroring the extractor/oauth seams. ``fake``
(default) is ConsoleEmailAdapter — it LOGS the activation link and never touches
the network (dev/CI). ``ses`` is AWS SES (UNVERIFIED-LIVE — a deploy human
precondition; CI never exercises it). Only the invite activation LINK is sent;
the raw invite token lives in memory only during create and is NEVER logged as a
secret (Hard Rule 2).

(Module named ``emailer`` deliberately, not ``email`` — the latter would sit
next to the stdlib ``email`` package boto3 itself imports.)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

from chefclaw.errors import ConfigError, EmailSendError

if TYPE_CHECKING:
    from chefclaw.config import Settings

logger = logging.getLogger(__name__)

__all__ = [
    "ConsoleEmailAdapter",
    "EmailAdapter",
    "SesEmailAdapter",
    "get_email_adapter",
]

_SUBJECT = "You're invited to chefclaw"


def _invite_body(activation_link: str) -> str:
    return (
        "You've been invited to chefclaw.\n\n"
        f"Activate your account (invite-only): {activation_link}\n"
    )


class EmailAdapter(Protocol):
    """The contract the invite flow sends through."""

    async def send_invite(self, *, to_email: str, activation_link: str) -> None: ...


class ConsoleEmailAdapter:
    """Fake adapter (default): logs the activation link, never sends. The link
    is ALSO surfaced in the create-invite response when chefclaw_email='fake'
    (``dev_activation_link``), so a solo dev never needs a real mailbox."""

    async def send_invite(self, *, to_email: str, activation_link: str) -> None:
        logger.info("invite email (console) → %s: %s", to_email, activation_link)


class SesEmailAdapter:
    """AWS SES via boto3 (UNVERIFIED-LIVE). boto3 is blocking, so the send runs
    in a worker thread (asyncio.to_thread). Creds come from the boto3 chain (an
    IAM role on the VPS preferred — never in code)."""

    def __init__(self, email_from: str, region: str) -> None:
        self._email_from = email_from
        self._region = region

    async def send_invite(self, *, to_email: str, activation_link: str) -> None:
        def _send() -> None:
            import boto3

            client = boto3.client("ses", region_name=self._region)
            client.send_email(
                Source=self._email_from,
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": _SUBJECT},
                    "Body": {"Text": {"Data": _invite_body(activation_link)}},
                },
            )

        try:
            await asyncio.to_thread(_send)
        except Exception as exc:  # pragma: no cover - deploy-time only
            # Never surface the recipient or boto internals to the client/logs.
            logger.warning("SES invite send failed", exc_info=True)
            raise EmailSendError("could not send the invite email") from exc


def get_email_adapter(settings: Settings) -> EmailAdapter:
    """Config-selected email adapter (``CHEFCLAW_EMAIL``), fail-closed.

    - ``fake`` (default) — ConsoleEmailAdapter, zero network, safe in CI.
    - ``ses`` — AWS SES; empty EMAIL_FROM/SES_REGION ⇒ ConfigError.
    - anything else — ConfigError (a typo must never silently pick a backend).
    """
    name = settings.chefclaw_email
    if name == "fake":
        return ConsoleEmailAdapter()
    if name == "ses":
        if not (settings.email_from and settings.ses_region):
            raise ConfigError(
                "CHEFCLAW_EMAIL=ses but EMAIL_FROM/SES_REGION is empty (fail-closed)."
            )
        return SesEmailAdapter(settings.email_from, settings.ses_region)
    raise ConfigError(f"Unknown CHEFCLAW_EMAIL value {name!r} — expected 'fake' or 'ses'.")
