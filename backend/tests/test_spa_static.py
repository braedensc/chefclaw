"""SPA fallback tests: a hard navigation / refresh on a client-side route
must serve index.html, while /api/* 404s stay JSON and real assets (present
or missing) keep exact StaticFiles behavior. No real database (see conftest).
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from chefclaw.config import get_settings
from tests.conftest import make_app

INDEX_HTML = "<!doctype html><title>chefclaw</title><div id=\"root\"></div>"
APP_JS = "console.log('chefclaw');"


@pytest.fixture
async def spa_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """Client against an app serving a minimal built SPA from a tmp dir.

    create_app() reads the static dir from the process-wide cached settings
    (not the request-time dependency), so the fixture goes through the env
    var + a cache clear — and clears again on teardown so no other test sees
    the tmp dir."""
    static_dir = tmp_path / "dist"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (static_dir / "assets" / "app.js").write_text(APP_JS, encoding="utf-8")
    monkeypatch.setenv("CHEFCLAW_STATIC_DIR", str(static_dir))
    get_settings.cache_clear()
    try:
        transport = ASGITransport(app=make_app())
        async with AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client
    finally:
        get_settings.cache_clear()


async def test_client_route_serves_index(spa_client: AsyncClient) -> None:
    """The reported bug: GET /settings on a fresh load must be the app,
    not {"detail":"Not Found"}."""
    response = await spa_client.get("/settings")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == INDEX_HTML


async def test_nested_client_route_serves_index(spa_client: AsyncClient) -> None:
    response = await spa_client.get("/recipes/01890000-0000-7000-8000-000000000001")
    assert response.status_code == 200
    assert response.text == INDEX_HTML


async def test_root_still_serves_index(spa_client: AsyncClient) -> None:
    response = await spa_client.get("/")
    assert response.status_code == 200
    assert response.text == INDEX_HTML


async def test_unknown_api_path_stays_json_404(spa_client: AsyncClient) -> None:
    response = await spa_client.get("/api/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_real_asset_served_as_is(spa_client: AsyncClient) -> None:
    response = await spa_client.get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == APP_JS
    assert "javascript" in response.headers["content-type"]


async def test_missing_asset_stays_404(spa_client: AsyncClient) -> None:
    """A file-shaped miss must fail loudly — serving index.html under a .js
    request would surface as an opaque MIME/parse error in the browser."""
    response = await spa_client.get("/assets/missing.js")
    assert response.status_code == 404
