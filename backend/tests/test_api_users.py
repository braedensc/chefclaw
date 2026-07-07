"""Admin user-management routes (V2-F) — CI tier: the users service is stubbed
(no DB); require_admin passes via the autouse admin-account stub (conftest). The
real SQL is exercised by the golden tier."""

import uuid

import pytest
from httpx import AsyncClient

from chefclaw import auth
from chefclaw.models import User
from chefclaw.services import users as users_service
from tests.conftest import OWNER_ID


def _user(**overrides) -> User:
    fields = dict(
        id=uuid.uuid4(),
        name="member",
        email="m@x.com",
        display_name="Member",
        is_admin=False,
        status="active",
        real_covers_enabled=False,
    )
    fields.update(overrides)
    return User(**fields)


async def test_list_users_returns_grants_and_no_secrets(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient
) -> None:
    rows = [_user(email="a@x.com"), _user(email="b@x.com", real_covers_enabled=True)]

    async def listing(sm):
        return rows

    monkeypatch.setattr(users_service, "list_users", listing)
    resp = await client.get("/api/admin/users")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {i["email"]: i["real_covers_enabled"] for i in items} == {
        "a@x.com": False,
        "b@x.com": True,
    }
    # Never leak an identity secret.
    assert all(
        "oauth_subject" not in i and "token_hash" not in i and "oauth_provider" not in i
        for i in items
    )


async def test_patch_user_sets_the_grant(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient
) -> None:
    uid = uuid.uuid4()
    captured: dict = {}

    async def setter(sm, user_id, enabled):
        captured["args"] = (user_id, enabled)
        return _user(id=user_id, real_covers_enabled=enabled)

    monkeypatch.setattr(users_service, "set_real_covers_enabled", setter)
    resp = await client.patch(f"/api/admin/users/{uid}", json={"real_covers_enabled": True})
    assert resp.status_code == 200
    assert resp.json()["real_covers_enabled"] is True
    assert captured["args"] == (uid, True)


async def test_patch_missing_user_is_404(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient
) -> None:
    async def setter(sm, user_id, enabled):
        return None

    monkeypatch.setattr(users_service, "set_real_covers_enabled", setter)
    resp = await client.patch(
        f"/api/admin/users/{uuid.uuid4()}", json={"real_covers_enabled": True}
    )
    assert resp.status_code == 404


async def test_patch_rejects_escalation_fields(client: AsyncClient) -> None:
    # extra="forbid" — no is_admin (or anything else) is settable through here.
    resp = await client.patch(
        f"/api/admin/users/{uuid.uuid4()}",
        json={"real_covers_enabled": True, "is_admin": True},
    )
    assert resp.status_code == 422


async def test_admin_users_require_admin(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient
) -> None:
    async def non_admin(owner_id: uuid.UUID) -> auth.Account:
        return auth.Account(id=OWNER_ID, name="friend", email="f@x", is_admin=False)

    monkeypatch.setattr(auth, "fetch_account", non_admin)
    listing = await client.get("/api/admin/users")
    patch = await client.patch(
        f"/api/admin/users/{uuid.uuid4()}", json={"real_covers_enabled": True}
    )
    assert listing.status_code == 403
    assert patch.status_code == 403
