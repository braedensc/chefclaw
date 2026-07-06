"""/api/health auth + shape tests (no real database — see conftest)."""

from httpx import AsyncClient

from tests.conftest import OWNER_ID, TEST_TOKEN, bearer


async def test_health_401_without_token(client: AsyncClient, ping_ok: None) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing bearer token."


async def test_health_401_with_wrong_token(client: AsyncClient, ping_ok: None) -> None:
    response = await client.get("/api/health", headers=bearer("wrong-token"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing bearer token."


async def test_health_401_when_no_token_configured(
    client_no_token: AsyncClient, ping_ok: None
) -> None:
    """Disabled-closed: empty configured token 401s EVERY request, even one
    presenting a token, with an actionable detail."""
    for headers in ({}, bearer("anything")):
        response = await client_no_token.get("/api/health", headers=headers)
        assert response.status_code == 401
        assert "CHEFCLAW_API_TOKEN" in response.json()["detail"]


async def test_health_200_full_shape(client: AsyncClient, ping_ok: None) -> None:
    response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "db": "ok",
        "sidecar": "not_configured",
        "cookie_freshness": "not_configured",
        "backup": "not_configured",
        "spend_month_usd": None,
    }


async def test_health_degraded_when_db_unreachable(
    client: AsyncClient, ping_down: None
) -> None:
    response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "unreachable"


async def test_owner_id_is_cached_seeded_owner(client: AsyncClient, ping_ok: None) -> None:
    """require_owner resolves (and caches) the stubbed seeded owner id."""
    from chefclaw import auth

    response = await client.get("/api/health", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    assert auth._cached_owner_id == OWNER_ID
