"""Extractor adapter tests — NO network, NO database.

The Gemini SDK client is replaced with an in-memory stub; the fail-closed
selection paths (§16.8) and the error-taxonomy mapping are the load-bearing
assertions here.
"""

import asyncio
import json
from importlib import resources
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from chefclaw.config import Settings
from chefclaw.errors import (
    ConfigError,
    ExtractionFailedError,
    RateLimitedError,
)
from chefclaw.extractors import (
    ExtractionOutcome,
    ExtractionUsage,
    ExtractorAdapter,
    get_extractor,
)
from chefclaw.extractors.fake import FakeExtractor
from chefclaw.extractors.gemini import PROMPT_VERSION, GeminiExtractor

VIDEO = Path("/nonexistent/video.mp4")

# Fake key assembled by concatenation — never a real-looking literal.
FAKE_KEY = "test-" + "key"


def make_settings(**overrides) -> Settings:
    """Settings isolated from the developer's real environment."""
    defaults = {
        "chefclaw_extractor": "fake",
        "gemini_api_key": "",
        "gemini_model": "gemini-test-model",
        "gemini_media_resolution": "low",
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ── get_extractor selection (fail-closed, §16.8) ────────────────────────────


def test_get_extractor_default_is_fake():
    extractor = get_extractor(make_settings())
    assert isinstance(extractor, FakeExtractor)
    assert isinstance(extractor, ExtractorAdapter)


def test_get_extractor_gemini_with_key():
    settings = make_settings(chefclaw_extractor="gemini", gemini_api_key=FAKE_KEY)
    extractor = get_extractor(settings)
    assert isinstance(extractor, GeminiExtractor)
    assert isinstance(extractor, ExtractorAdapter)


def test_get_extractor_gemini_without_key_fails_closed():
    settings = make_settings(chefclaw_extractor="gemini", gemini_api_key="")
    with pytest.raises(ConfigError):
        get_extractor(settings)


def test_get_extractor_unknown_name_is_config_error():
    with pytest.raises(ConfigError):
        get_extractor(make_settings(chefclaw_extractor="gpt9000"))


def test_get_extractor_bad_media_resolution_is_config_error():
    settings = make_settings(
        chefclaw_extractor="gemini", gemini_api_key=FAKE_KEY, gemini_media_resolution="ultra"
    )
    with pytest.raises(ConfigError):
        get_extractor(settings)


# ── FakeExtractor ────────────────────────────────────────────────────────────


async def test_fake_default_dish_is_bilingual_and_faithful():
    outcome = await FakeExtractor().extract(VIDEO, "红烧肉教程", 300)
    assert isinstance(outcome, ExtractionOutcome)
    assert len(outcome.dishes) == 1
    dish = outcome.dishes[0]
    assert dish["dish_name"]["original"] == "红烧肉"
    assert dish["dish_name"]["en"]
    assert "source" not in dish  # provenance is injected by the pipeline, never the extractor
    # The 适量 ingredient obeys the invariant: value null, unit null, approx.
    approx = next(i for i in dish["ingredients"] if i["quantity"]["raw_text"] == "适量")
    assert approx["quantity"]["value"] is None
    assert approx["quantity"]["unit"] is None
    assert approx["quantity"]["unit_type"] == "approx"
    assert approx["quantity_grams_stated"] is None
    # Grams only where explicitly stated.
    stated = next(i for i in dish["ingredients"] if i["raw_text"] == "五花肉500克")
    assert stated["quantity_grams_stated"] == 500
    assert [s["step_number"] for s in dish["steps"]] == [1, 2, 3]


async def test_fake_default_dish_passes_documents_schema():
    """Coordination guard: the canned fixture must satisfy the documents layer."""
    # Local import: the documents module belongs to the pipeline half of Phase 2.
    from chefclaw.documents import SourceInfo, validate_extraction

    outcome = await FakeExtractor().extract(VIDEO, None, None)
    source = SourceInfo(
        platform="local", url="file:///video.mp4", creator=None, video_duration_seconds=None
    )
    documents = validate_extraction(outcome.dishes, source)
    assert len(documents) == 1
    assert documents[0].dish_name.original == "红烧肉"


async def test_fake_usage_is_deterministic():
    first = await FakeExtractor().extract(VIDEO, None, None)
    second = await FakeExtractor().extract(VIDEO, None, None)
    assert first.usage == second.usage
    assert first.usage.tokens_thinking == 0
    assert first.usage.prompt_version == "v1"


async def test_fake_injection_of_dishes_and_warnings():
    dishes = [
        {"dish_name": {"en": "A", "original": "甲"}},
        {"dish_name": {"en": "B", "original": "乙"}},
    ]
    fake = FakeExtractor(dishes=dishes, warnings=["low audio"])
    outcome = await fake.extract(VIDEO, None, None)
    assert len(outcome.dishes) == 2
    assert outcome.warnings == ["low audio"]
    # Returned dishes are copies — mutating them must not poison later calls.
    outcome.dishes[0]["dish_name"]["en"] = "MUTATED"
    again = await fake.extract(VIDEO, None, None)
    assert again.dishes[0]["dish_name"]["en"] == "A"


async def test_fake_failure_injection_raises_verbatim():
    boom = RateLimitedError("injected throttle")
    fake = FakeExtractor(failure=boom)
    with pytest.raises(RateLimitedError) as exc_info:
        await fake.extract(VIDEO, None, None)
    assert exc_info.value is boom


async def test_fake_records_calls():
    fake = FakeExtractor()
    await fake.extract(VIDEO, "title", 120)
    await fake.extract(VIDEO, None, None)
    assert len(fake.calls) == 2
    assert fake.calls[0].source_title == "title"
    assert fake.calls[0].source_duration_seconds == 120


# ── GeminiExtractor with a stubbed SDK client ───────────────────────────────


class StubFiles:
    """Stand-in for client.aio.files."""

    def __init__(self, upload_result=None, get_results=None, upload_error=None):
        self.upload_result = upload_result
        self.get_results = list(get_results or [])
        self.upload_error = upload_error
        self.deleted: list[str] = []
        self.uploaded_paths: list[object] = []

    async def upload(self, *, file, config=None):
        if self.upload_error is not None:
            raise self.upload_error
        self.uploaded_paths.append(file)
        return self.upload_result

    async def get(self, *, name, config=None):
        return self.get_results.pop(0)

    async def delete(self, *, name, config=None):
        self.deleted.append(name)


class StubModels:
    """Stand-in for client.aio.models."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    async def generate_content(self, *, model, contents, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error is not None:
            raise self.error
        return self.response


def stub_client(files: StubFiles, models: StubModels):
    return SimpleNamespace(aio=SimpleNamespace(files=files, models=models))


def active_file(name: str = "files/test-upload") -> genai_types.File:
    return genai_types.File(name=name, state=genai_types.FileState.ACTIVE)


def processing_file(name: str = "files/test-upload") -> genai_types.File:
    return genai_types.File(name=name, state=genai_types.FileState.PROCESSING)


def gemini_response(text, usage=None):
    return SimpleNamespace(text=text, usage_metadata=usage)


def make_gemini(files: StubFiles, models: StubModels, **settings_overrides) -> GeminiExtractor:
    settings = make_settings(
        chefclaw_extractor="gemini", gemini_api_key=FAKE_KEY, **settings_overrides
    )
    return GeminiExtractor(
        settings, client=stub_client(files, models), poll_interval_seconds=0
    )


def api_error(code: int, status: str, message: str = "boom") -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"message": message, "status": status}})


DISHES = [{"dish_name": {"en": "Mapo tofu", "original": "麻婆豆腐"}, "ingredients": []}]


async def test_gemini_happy_path_upload_wait_generate_parse():
    usage = SimpleNamespace(
        prompt_token_count=1200, candidates_token_count=340, thoughts_token_count=None
    )
    files = StubFiles(upload_result=processing_file(), get_results=[active_file()])
    models = StubModels(response=gemini_response(json.dumps(DISHES), usage))
    extractor = make_gemini(files, models)

    outcome = await extractor.extract(VIDEO, "麻婆豆腐做法", 240)

    assert outcome.dishes == DISHES
    assert outcome.usage == ExtractionUsage(
        model_id="gemini-test-model",
        prompt_version="v1",
        tokens_in=1200,
        tokens_out=340,
        tokens_thinking=0,  # thinking disabled — SDK reports None, recorded as 0
    )
    assert outcome.warnings == []
    # Exactly one paid call, against the CONFIGURED model id (never hardcoded).
    assert len(models.calls) == 1
    assert models.calls[0]["model"] == "gemini-test-model"
    config = models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.thinking_config.thinking_budget == 0
    assert config.media_resolution == genai_types.MediaResolution.MEDIA_RESOLUTION_LOW
    assert config.temperature <= 0.2
    # The prompt + source context reached the model alongside the file.
    prompt_sent = models.calls[0]["contents"][1]
    assert "适量" in prompt_sent
    assert "麻婆豆腐做法" in prompt_sent
    assert "240 seconds" in prompt_sent
    # Files-API hygiene: uploaded file deleted afterwards.
    assert files.deleted == ["files/test-upload"]


async def test_gemini_json_garbage_raises_extraction_failed_preserving_raw():
    raw = "Sure! Here is the recipe: 红烧肉..."
    files = StubFiles(upload_result=active_file())
    models = StubModels(response=gemini_response(raw))
    extractor = make_gemini(files, models)

    with pytest.raises(ExtractionFailedError) as exc_info:
        await extractor.extract(VIDEO, None, None)
    assert exc_info.value.raw_text == raw
    assert "红烧肉" in str(exc_info.value)
    assert files.deleted == ["files/test-upload"]  # cleanup still ran


async def test_gemini_parse_failure_carries_usage_when_sdk_surfaced_it():
    """A billed-but-unparseable response must hand its token accounting to the
    worker (via the error) so the ledger records real tokens, not zeros."""
    usage = SimpleNamespace(
        prompt_token_count=1200, candidates_token_count=340, thoughts_token_count=None
    )
    files = StubFiles(upload_result=active_file())
    models = StubModels(response=gemini_response("not json at all", usage))
    extractor = make_gemini(files, models)

    with pytest.raises(ExtractionFailedError) as exc_info:
        await extractor.extract(VIDEO, None, None)
    carried = exc_info.value.usage
    assert carried == ExtractionUsage(
        model_id="gemini-test-model",
        prompt_version="v1",
        tokens_in=1200,
        tokens_out=340,
        tokens_thinking=0,
    )


async def test_gemini_parse_failure_without_metadata_carries_no_usage():
    files = StubFiles(upload_result=active_file())
    models = StubModels(response=gemini_response("not json at all", usage=None))
    extractor = make_gemini(files, models)

    with pytest.raises(ExtractionFailedError) as exc_info:
        await extractor.extract(VIDEO, None, None)
    assert exc_info.value.usage is None  # worker ledgers zeros (unchanged contract)


async def test_gemini_non_array_json_raises_extraction_failed_preserving_raw():
    raw = json.dumps({"dish_name": {"en": "solo", "original": "单"}})
    files = StubFiles(upload_result=active_file())
    models = StubModels(response=gemini_response(raw))
    extractor = make_gemini(files, models)

    with pytest.raises(ExtractionFailedError) as exc_info:
        await extractor.extract(VIDEO, None, None)
    assert exc_info.value.raw_text == raw


async def test_gemini_429_maps_to_rate_limited():
    files = StubFiles(upload_result=active_file())
    models = StubModels(error=api_error(429, "RESOURCE_EXHAUSTED", "quota exceeded"))
    extractor = make_gemini(files, models)

    with pytest.raises(RateLimitedError):
        await extractor.extract(VIDEO, None, None)
    assert files.deleted == ["files/test-upload"]


async def test_gemini_auth_error_maps_to_config_error():
    files = StubFiles(upload_result=active_file())
    models = StubModels(error=api_error(401, "UNAUTHENTICATED", "API key not valid"))
    extractor = make_gemini(files, models)

    with pytest.raises(ConfigError):
        await extractor.extract(VIDEO, None, None)


async def test_gemini_server_error_maps_to_extraction_failed():
    files = StubFiles(upload_result=active_file())
    models = StubModels(error=api_error(500, "INTERNAL", "backend exploded"))
    extractor = make_gemini(files, models)

    with pytest.raises(ExtractionFailedError):
        await extractor.extract(VIDEO, None, None)


async def test_gemini_upload_throttle_maps_to_rate_limited_and_skips_delete():
    files = StubFiles(upload_error=api_error(429, "RESOURCE_EXHAUSTED"))
    models = StubModels()
    extractor = make_gemini(files, models)

    with pytest.raises(RateLimitedError):
        await extractor.extract(VIDEO, None, None)
    assert files.deleted == []  # nothing was uploaded, nothing to clean
    assert models.calls == []  # and no paid generate call happened


async def test_gemini_file_processing_failure_raises_extraction_failed():
    failed = genai_types.File(
        name="files/test-upload",
        state=genai_types.FileState.FAILED,
        error=genai_types.FileStatus(message="unsupported codec"),
    )
    files = StubFiles(upload_result=processing_file(), get_results=[failed])
    models = StubModels()
    extractor = make_gemini(files, models)

    with pytest.raises(ExtractionFailedError):
        await extractor.extract(VIDEO, None, None)
    assert files.deleted == ["files/test-upload"]
    assert models.calls == []  # never reached the paid call


async def test_gemini_missing_usage_metadata_warns_and_zeroes():
    files = StubFiles(upload_result=active_file())
    models = StubModels(response=gemini_response(json.dumps(DISHES), usage=None))
    extractor = make_gemini(files, models)

    outcome = await extractor.extract(VIDEO, None, None)
    assert outcome.usage.tokens_in == 0
    assert outcome.usage.tokens_out == 0
    assert outcome.usage.tokens_thinking == 0
    assert any("usage_metadata" in w for w in outcome.warnings)


async def test_gemini_worker_cancellation_mid_poll_still_deletes_upload():
    """The worker's per-stage timeout cancels us mid-poll (the designed
    deadline path) — the Files-API upload must not leak."""
    files = StubFiles(upload_result=processing_file(), get_results=[processing_file()] * 50)
    models = StubModels()
    settings = make_settings(chefclaw_extractor="gemini", gemini_api_key=FAKE_KEY)
    extractor = GeminiExtractor(
        settings, client=stub_client(files, models), poll_interval_seconds=60
    )

    task = asyncio.ensure_future(extractor.extract(VIDEO, None, None))
    for _ in range(10):  # let the task reach the poll sleep
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert files.deleted == ["files/test-upload"]  # cleaned up despite the cancel
    assert models.calls == []  # never reached the paid call


async def test_gemini_unexpected_poll_error_propagates_and_deletes_upload():
    class ExplodingGetFiles(StubFiles):
        async def get(self, *, name, config=None):
            raise RuntimeError("transport blew up outside APIError")

    files = ExplodingGetFiles(upload_result=processing_file())
    models = StubModels()
    extractor = make_gemini(files, models)

    with pytest.raises(RuntimeError):
        await extractor.extract(VIDEO, None, None)
    assert files.deleted == ["files/test-upload"]


async def test_gemini_cleanup_errors_never_fail_extraction():
    class ExplodingDeleteFiles(StubFiles):
        async def delete(self, *, name, config=None):
            raise api_error(500, "INTERNAL", "delete broke")

    files = ExplodingDeleteFiles(upload_result=active_file())
    models = StubModels(response=gemini_response(json.dumps(DISHES)))
    extractor = make_gemini(files, models)

    outcome = await extractor.extract(VIDEO, None, None)  # must not raise
    assert outcome.dishes == DISHES


# ── prompt file guards ───────────────────────────────────────────────────────


def prompt_text() -> str:
    return (
        resources.files("chefclaw").joinpath("prompts/extract_v1.md").read_text(encoding="utf-8")
    )


def test_prompt_exists_and_is_not_gutted():
    text = prompt_text()
    assert text.strip(), "extract_v1.md must not be empty"
    # Literal markers guarding against accidental gutting of the invariant.
    assert "适量" in text
    assert "JSON" in text
    assert "never" in text


def test_prompt_version_is_v1():
    assert PROMPT_VERSION == "v1"


async def test_gemini_stamps_prompt_version_v1():
    files = StubFiles(upload_result=active_file())
    models = StubModels(response=gemini_response(json.dumps(DISHES)))
    extractor = make_gemini(files, models)
    outcome = await extractor.extract(VIDEO, None, None)
    assert outcome.usage.prompt_version == "v1"
