"""API transport tests — extract/upload/jobs/library routes. CI tier: the
JobStore is faked, the library service functions are monkeypatched, so no
database (and no network) is ever touched."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chefclaw import db
from chefclaw.app import create_app
from chefclaw.config import Settings, get_settings
from chefclaw.extractors.fake import default_dish
from chefclaw.models import Recipe
from chefclaw.routers.deps import get_job_store, get_source_adapters
from chefclaw.services import recipes as recipes_service
from chefclaw.sources.fake import FakeSource
from tests.conftest import OWNER_ID, TEST_TOKEN, bearer
from tests.fakes import FakeJobStore

FAKE_URL = "https://fake.example/video/1"


def build_app(
    store: FakeJobStore | None = None,
    adapters: list | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings or Settings(
        chefclaw_api_token=TEST_TOKEN
    )
    app.dependency_overrides[get_job_store] = lambda: store or FakeJobStore()
    app.dependency_overrides[get_source_adapters] = lambda: (
        adapters
        if adapters is not None
        else [FakeSource(platform="bilibili", canonical_id="BVtest00001-p1")]
    )
    # The library routes take a session dependency; the service functions are
    # monkeypatched in these tests, so no session may ever be built (the
    # local compose DB is production — kit inversion).
    app.dependency_overrides[db.get_session] = lambda: None
    return app


def client_for(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def make_recipe_row(**overrides) -> Recipe:
    document = default_dish()
    document["source"] = {
        "platform": "bilibili",
        "url": FAKE_URL,
        "creator": None,
        "video_duration_seconds": None,
    }
    fields = dict(
        id=uuid.uuid4(),
        owner_id=OWNER_ID,
        title_en="Red-braised pork belly",
        title_original="红烧肉",
        platform="bilibili",
        source_url=FAKE_URL,
        canonical_id="BVtest00001-p1",
        dish_index=0,
        status="stored",
        tags=["pork"],
        user_notes=None,
        document=document,
        extraction_meta={"model_id": "fake-extractor"},
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    fields.update(overrides)
    return Recipe(**fields)


# ─── POST /api/recipes/extract ───────────────────────────────────────────────


async def test_extract_new_job_202_returns_job_resource() -> None:
    store = FakeJobStore()
    async with client_for(build_app(store)) as client:
        response = await client.post(
            "/api/recipes/extract", json={"url": FAKE_URL}, headers=bearer(TEST_TOKEN)
        )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["type"] == "extract"
    assert (body["platform"], body["canonical_id"]) == ("bilibili", "BVtest00001-p1")
    assert body["result_recipe_ids"] == []
    assert body["url"] == FAKE_URL  # the originally pasted URL — the retry affordance re-POSTs it
    assert {"id", "attempts", "error_type", "error_detail", "created_at", "updated_at"} <= set(
        body
    )
    assert "payload" not in body  # internal detail, not part of the contract


async def test_extract_duplicate_200_same_job() -> None:
    store = FakeJobStore()
    async with client_for(build_app(store)) as client:
        first = await client.post(
            "/api/recipes/extract", json={"url": FAKE_URL}, headers=bearer(TEST_TOKEN)
        )
        second = await client.post(
            "/api/recipes/extract", json={"url": FAKE_URL}, headers=bearer(TEST_TOKEN)
        )
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


async def test_extract_unsupported_url_400_typed() -> None:
    async with client_for(build_app()) as client:
        response = await client.post(
            "/api/recipes/extract",
            json={"url": "https://unknown.example/x"},
            headers=bearer(TEST_TOKEN),
        )
    assert response.status_code == 400
    body = response.json()
    assert body["error_type"] == "unsupported_url"
    assert "detail" in body


async def test_extract_rednote_without_sidecar_503_typed() -> None:
    adapters = [FakeSource(platform="rednote", canonical_id="a" * 24)]
    async with client_for(build_app(adapters=adapters)) as client:
        response = await client.post(
            "/api/recipes/extract", json={"url": FAKE_URL}, headers=bearer(TEST_TOKEN)
        )
    assert response.status_code == 503
    body = response.json()
    assert body["error_type"] == "config_error"
    assert "XHS_SIDECAR_URL" in body["detail"]


async def test_extract_requires_auth() -> None:
    async with client_for(build_app()) as client:
        response = await client.post("/api/recipes/extract", json={"url": FAKE_URL})
    assert response.status_code == 401


# ─── POST /api/recipes/upload ────────────────────────────────────────────────


async def test_upload_202_then_rehash_200(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = Settings(chefclaw_api_token=TEST_TOKEN, scratch_dir=str(tmp_path))
    app = build_app(store, settings=settings)
    async with client_for(app) as client:
        first = await client.post(
            "/api/recipes/upload",
            files={"file": ("dinner.mp4", b"same video bytes", "video/mp4")},
            data={"provenance_url": "https://example.test/post", "platform_hint": "rednote"},
            headers=bearer(TEST_TOKEN),
        )
        second = await client.post(
            "/api/recipes/upload",
            files={"file": ("renamed.mp4", b"same video bytes", "video/mp4")},
            headers=bearer(TEST_TOKEN),
        )
    assert first.status_code == 202
    body = first.json()
    assert body["type"] == "upload"
    assert body["platform"] == "local"
    assert body["canonical_id"].startswith("file-")
    assert second.status_code == 200
    assert second.json()["id"] == body["id"]


async def test_upload_413_when_content_length_exceeds_cap(tmp_path: Path) -> None:
    """The middleware rejects an over-cap upload via Content-Length BEFORE the
    body is parsed — so the handler never runs and nothing is spooled to our
    incoming dir (an unbounded upload endpoint could otherwise fill the disk)."""
    store = FakeJobStore()
    settings = Settings(chefclaw_api_token=TEST_TOKEN, scratch_dir=str(tmp_path))
    app = build_app(store, settings=settings)
    app.state.max_upload_bytes = 100  # tiny cap; the multipart body far exceeds it
    async with client_for(app) as client:
        resp = await client.post(
            "/api/recipes/upload",
            files={"file": ("big.mp4", b"x" * 500, "video/mp4")},
            headers=bearer(TEST_TOKEN),
        )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error_type"] == "upload_too_large"
    assert "MAX_UPLOAD_MB" in body["detail"]
    # Rejected pre-parse: the handler never created its incoming dir.
    assert not (tmp_path / "chefclaw-uploads" / "incoming").exists()


async def test_upload_streaming_guard_rejects_over_settings_cap(tmp_path: Path) -> None:
    """Backstop for a Content-Length-less (chunked) upload: the middleware
    passes (body < the default app-state cap), and the handler's streaming
    guard bounds the bytes it writes to MAX_UPLOAD_MB, aborting with a typed
    413 and cleaning up the partial file."""
    store = FakeJobStore()
    settings = Settings(
        chefclaw_api_token=TEST_TOKEN, scratch_dir=str(tmp_path), max_upload_mb=1
    )
    app = build_app(store, settings=settings)  # app.state cap stays the 500 MB default
    over_cap = b"x" * (1024 * 1024 + 2048)  # > 1 MB, the settings cap
    async with client_for(app) as client:
        resp = await client.post(
            "/api/recipes/upload",
            files={"file": ("big.mp4", over_cap, "video/mp4")},
            headers=bearer(TEST_TOKEN),
        )
    assert resp.status_code == 413
    assert resp.json()["error_type"] == "upload_too_large"
    incoming = tmp_path / "chefclaw-uploads" / "incoming"
    assert not incoming.exists() or not any(incoming.iterdir())


# ─── GET /api/jobs/{id} ──────────────────────────────────────────────────────


async def test_get_job_200_and_owner_scoped_404() -> None:
    store = FakeJobStore()
    mine = store.seed_job(owner_id=OWNER_ID, status="failed")
    mine.error_type = "download_failed"
    mine.error_detail = "cdn hiccup"
    theirs = store.seed_job(owner_id=uuid.uuid4(), canonical_id="BVother")
    async with client_for(build_app(store)) as client:
        ok = await client.get(f"/api/jobs/{mine.id}", headers=bearer(TEST_TOKEN))
        other = await client.get(f"/api/jobs/{theirs.id}", headers=bearer(TEST_TOKEN))
        missing = await client.get(f"/api/jobs/{uuid.uuid4()}", headers=bearer(TEST_TOKEN))
    assert ok.status_code == 200
    body = ok.json()
    assert (body["status"], body["error_type"], body["error_detail"]) == (
        "failed",
        "download_failed",
        "cdn hiccup",
    )
    assert other.status_code == 404  # someone else's job is invisible
    assert other.json()["error_type"] == "not_found"
    assert missing.status_code == 404


async def test_get_job_url_lifted_from_payload_and_none_when_absent() -> None:
    store = FakeJobStore()
    with_url = store.seed_job(owner_id=OWNER_ID)
    without_url = store.seed_job(owner_id=OWNER_ID, canonical_id="BVnourl", payload={})
    async with client_for(build_app(store)) as client:
        first = await client.get(f"/api/jobs/{with_url.id}", headers=bearer(TEST_TOKEN))
        second = await client.get(f"/api/jobs/{without_url.id}", headers=bearer(TEST_TOKEN))
    assert first.json()["url"] == "https://example.test/v"
    assert second.status_code == 200
    assert second.json()["url"] is None


# ─── GET /api/jobs (jobs drawer list) ────────────────────────────────────────


async def test_list_jobs_shape_ordering_and_owner_scope() -> None:
    store = FakeJobStore()
    oldest = store.seed_job(owner_id=OWNER_ID, canonical_id="BVone", status="stored")
    newest = store.seed_job(
        owner_id=OWNER_ID,
        canonical_id="BVtwo",
        status="failed",
        payload={"url": "fake://two", "fetch_url": "fake://two"},
    )
    store.seed_job(owner_id=uuid.uuid4(), canonical_id="BVtheirs")  # invisible
    async with client_for(build_app(store)) as client:
        response = await client.get("/api/jobs", headers=bearer(TEST_TOKEN))
    assert response.status_code == 200
    body = response.json()
    # Newest activity first (updated_at DESC), someone else's jobs excluded.
    assert [item["id"] for item in body] == [str(newest.id), str(oldest.id)]
    assert body[0]["url"] == "fake://two"
    assert body[1]["url"] == "https://example.test/v"
    assert all("payload" not in item for item in body)


async def test_list_jobs_limit_default_and_cap() -> None:
    store = FakeJobStore()
    for index in range(25):
        store.seed_job(owner_id=OWNER_ID, canonical_id=f"BV{index}")
    async with client_for(build_app(store)) as client:
        default = await client.get("/api/jobs", headers=bearer(TEST_TOKEN))
        one = await client.get("/api/jobs", params={"limit": 1}, headers=bearer(TEST_TOKEN))
        over = await client.get("/api/jobs", params={"limit": 101}, headers=bearer(TEST_TOKEN))
    assert len(default.json()) == 20  # default limit
    assert len(one.json()) == 1
    assert over.status_code == 422  # le=100


# ─── GET /api/recipes (library list) ─────────────────────────────────────────


async def test_list_recipes_page_shape_and_filter_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    row = make_recipe_row()

    async def fake_list(session, owner_id, **kwargs):
        captured["owner_id"] = owner_id
        captured.update(kwargs)
        return [row], 42

    monkeypatch.setattr(recipes_service, "list_recipes", fake_list)
    async with client_for(build_app()) as client:
        response = await client.get(
            "/api/recipes",
            params={"q": "pork", "platform": "bilibili", "tag": "pork", "sort": "oldest",
                    "limit": 10, "offset": 20},
            headers=bearer(TEST_TOKEN),
        )
    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["limit"], body["offset"]) == (42, 10, 20)
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["title_original"] == "红烧肉"
    assert "document" not in item  # summaries stay light
    assert captured == {
        "owner_id": OWNER_ID,
        "q": "pork",
        "platform": "bilibili",
        "tag": "pork",
        "sort": "oldest",
        "limit": 10,
        "offset": 20,
    }


# ─── GET /api/recipes/{id} ───────────────────────────────────────────────────


async def test_get_recipe_detail_includes_document(monkeypatch: pytest.MonkeyPatch) -> None:
    row = make_recipe_row()

    async def fake_get(session, owner_id, recipe_id):
        return row if recipe_id == row.id else None

    monkeypatch.setattr(recipes_service, "get_recipe", fake_get)
    async with client_for(build_app()) as client:
        found = await client.get(f"/api/recipes/{row.id}", headers=bearer(TEST_TOKEN))
        missing = await client.get(f"/api/recipes/{uuid.uuid4()}", headers=bearer(TEST_TOKEN))
    assert found.status_code == 200
    body = found.json()
    assert body["document"]["dish_name"]["original"] == "红烧肉"
    assert body["source_url"] == FAKE_URL
    assert missing.status_code == 404
    assert missing.json()["error_type"] == "not_found"


# ─── PATCH /api/recipes/{id} ─────────────────────────────────────────────────


async def test_patch_updates_only_provided_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    row = make_recipe_row()
    captured: dict = {}

    async def fake_patch(session, owner_id, recipe_id, **kwargs):
        captured.update(kwargs)
        row.tags = kwargs.get("tags", row.tags)
        return row

    monkeypatch.setattr(recipes_service, "patch_recipe", fake_patch)
    async with client_for(build_app()) as client:
        response = await client.patch(
            f"/api/recipes/{row.id}", json={"tags": ["dinner"]}, headers=bearer(TEST_TOKEN)
        )
    assert response.status_code == 200
    assert captured == {"tags": ["dinner"]}  # user_notes absent ⇒ untouched
    assert response.json()["tags"] == ["dinner"]


@pytest.mark.parametrize(
    "body",
    [
        {"document": {"dish_name": {"en": "Hacked"}}},
        {"title_en": "Hacked"},
        {"tags": ["ok"], "document": {}},
        {"status": "failed"},
    ],
)
async def test_patch_rejects_document_and_other_field_edits(
    monkeypatch: pytest.MonkeyPatch, body: dict
) -> None:
    """The document is NEVER user-editable — a PATCH mentioning it (or any
    non-editable field) is a 422 and the service is never called."""
    called = False

    async def fake_patch(session, owner_id, recipe_id, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(recipes_service, "patch_recipe", fake_patch)
    async with client_for(build_app()) as client:
        response = await client.patch(
            f"/api/recipes/{uuid.uuid4()}", json=body, headers=bearer(TEST_TOKEN)
        )
    assert response.status_code == 422
    assert called is False


# ─── DELETE /api/recipes/{id} ────────────────────────────────────────────────


async def test_delete_recipe_204_and_404(monkeypatch: pytest.MonkeyPatch) -> None:
    row_id = uuid.uuid4()

    async def fake_delete(session, owner_id, recipe_id):
        return recipe_id == row_id

    monkeypatch.setattr(recipes_service, "delete_recipe", fake_delete)
    async with client_for(build_app()) as client:
        gone = await client.delete(f"/api/recipes/{row_id}", headers=bearer(TEST_TOKEN))
        missing = await client.delete(f"/api/recipes/{uuid.uuid4()}", headers=bearer(TEST_TOKEN))
    assert gone.status_code == 204
    assert gone.content == b""
    assert missing.status_code == 404
    assert missing.json()["error_type"] == "not_found"


# ─── auth is required everywhere ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/recipes"),
        ("GET", f"/api/recipes/{uuid.uuid4()}"),
        ("GET", "/api/jobs"),
        ("GET", f"/api/jobs/{uuid.uuid4()}"),
        ("PATCH", f"/api/recipes/{uuid.uuid4()}"),
        ("DELETE", f"/api/recipes/{uuid.uuid4()}"),
    ],
)
async def test_all_routes_require_bearer_token(method: str, path: str) -> None:
    async with client_for(build_app()) as client:
        response = await client.request(method, path, json={} if method == "PATCH" else None)
    assert response.status_code == 401


async def test_upload_requires_auth(tmp_path: Path) -> None:
    """The upload route must 401 without a token — and must do so even when a
    file body is present (auth must not be short-circuited by body parsing)."""
    settings = Settings(chefclaw_api_token=TEST_TOKEN, scratch_dir=str(tmp_path))
    async with client_for(build_app(settings=settings)) as client:
        bare = await client.post("/api/recipes/upload")
        with_body = await client.post(
            "/api/recipes/upload",
            files={"file": ("dinner.mp4", b"bytes", "video/mp4")},
        )
    assert bare.status_code == 401
    assert with_body.status_code == 401
    # Nothing may land on disk for an unauthenticated request:
    incoming = tmp_path / "chefclaw-uploads" / "incoming"
    assert not incoming.exists() or not any(incoming.iterdir())
