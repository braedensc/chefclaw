"""QwenExtractor tests — NO network, NO database.

Mirrors the Gemini suite: an in-memory stub stands in for the httpx client;
the load-bearing assertions are fail-closed selection (§16.8), the typed
error-taxonomy mapping, and faithful parse behavior (raw output preserved,
usage carried on billed-but-unparseable responses).

The adapter itself is UNVERIFIED-LIVE (no DashScope key exists; the human
region/data-governance review in docs/SERVICES.md precedes first real use) —
these tests pin the implementation to the DOCUMENTED request/response shape.
"""

import base64
import json
from pathlib import Path

import httpx
import pytest

from chefclaw.errors import ConfigError, ExtractionFailedError, RateLimitedError
from chefclaw.extractors import (
    ExtractionUsage,
    ExtractorAdapter,
    extractor_model_id,
    get_extractor,
)
from chefclaw.extractors.qwen import QwenExtractor
from tests.test_extractors import FAKE_KEY, make_settings

DISHES = [{"dish_name": {"en": "Mapo tofu", "original": "麻婆豆腐"}, "ingredients": []}]


def qwen_settings(**overrides):
    defaults = {"chefclaw_extractor": "qwen", "dashscope_api_key": FAKE_KEY}
    defaults.update(overrides)
    return make_settings(**defaults)


# ── selection (fail-closed, §16.8) ───────────────────────────────────────────


def test_get_extractor_qwen_with_key():
    extractor = get_extractor(qwen_settings())
    assert isinstance(extractor, QwenExtractor)
    assert isinstance(extractor, ExtractorAdapter)


def test_get_extractor_qwen_without_key_fails_closed():
    with pytest.raises(ConfigError, match="DASHSCOPE_API_KEY"):
        get_extractor(qwen_settings(dashscope_api_key=""))


def test_qwen_empty_model_id_is_config_error():
    with pytest.raises(ConfigError, match="DASHSCOPE_MODEL"):
        get_extractor(qwen_settings(dashscope_model=""))


def test_extractor_model_id_for_qwen_is_the_dashscope_model():
    settings = qwen_settings(dashscope_model="qwen-test-model")
    assert extractor_model_id(settings) == "qwen-test-model"


# ── stub httpx client ────────────────────────────────────────────────────────


class StubHttpClient:
    """Stand-in for httpx.AsyncClient: records the request, returns/raises."""

    def __init__(self, response: httpx.Response | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    async def post(self, url, *, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if self.error is not None:
            raise self.error
        return self.response


def chat_response(content, usage: dict | None = None, status: int = 200) -> httpx.Response:
    body: dict = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(status, json=body)


def make_qwen(client: StubHttpClient, **settings_overrides) -> QwenExtractor:
    settings = qwen_settings(dashscope_model="qwen-test-model", **settings_overrides)
    return QwenExtractor(settings, client=client)  # type: ignore[arg-type]


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"tiny fake video bytes")
    return path


USAGE = {"prompt_tokens": 2509, "completion_tokens": 34, "total_tokens": 2543}


# ── happy path ───────────────────────────────────────────────────────────────


async def test_qwen_happy_path_documented_request_shape(video: Path):
    client = StubHttpClient(response=chat_response(json.dumps(DISHES), USAGE))
    extractor = make_qwen(client)

    outcome = await extractor.extract(video, "麻婆豆腐做法", 240)

    assert outcome.dishes == DISHES
    assert outcome.usage == ExtractionUsage(
        model_id="qwen-test-model",
        prompt_version="v2",
        tokens_in=2509,
        tokens_out=34,
        tokens_thinking=0,
    )
    assert outcome.warnings == []

    # Exactly one paid call, against the documented compatible-mode endpoint.
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    payload = call["json"]
    assert payload["model"] == "qwen-test-model"  # configured, never hardcoded
    assert payload["temperature"] <= 0.2
    content = payload["messages"][0]["content"]
    # Documented video content item: {"type": "video_url", "video_url": {"url": …}}
    video_item = content[0]
    assert video_item["type"] == "video_url"
    encoded = base64.b64encode(b"tiny fake video bytes").decode("ascii")
    assert video_item["video_url"]["url"] == f"data:video/mp4;base64,{encoded}"
    # The prompt + source context reached the model:
    text_item = content[1]
    assert text_item["type"] == "text"
    assert "适量" in text_item["text"]
    assert "麻婆豆腐做法" in text_item["text"]
    assert "240 seconds" in text_item["text"]


async def test_qwen_base_url_is_config(video: Path):
    client = StubHttpClient(response=chat_response(json.dumps(DISHES), USAGE))
    extractor = make_qwen(client, dashscope_base_url="https://example.test/compat/v1/")
    await extractor.extract(video, None, None)
    assert client.calls[0]["url"] == "https://example.test/compat/v1/chat/completions"


async def test_qwen_missing_usage_warns_and_zeroes(video: Path):
    client = StubHttpClient(response=chat_response(json.dumps(DISHES), usage=None))
    extractor = make_qwen(client)
    outcome = await extractor.extract(video, None, None)
    assert outcome.usage.tokens_in == 0
    assert outcome.usage.tokens_out == 0
    assert any("usage" in w for w in outcome.warnings)


# ── error mapping (typed taxonomy) ───────────────────────────────────────────


def error_response(status: int, code: str, message: str = "boom") -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"message": message, "type": "test_error", "code": code}}
    )


async def test_qwen_429_maps_to_rate_limited(video: Path):
    client = StubHttpClient(response=error_response(429, "rate_limit_exceeded"))
    with pytest.raises(RateLimitedError):
        await make_qwen(client).extract(video, None, None)


async def test_qwen_auth_error_maps_to_config_error(video: Path):
    client = StubHttpClient(response=error_response(401, "invalid_api_key"))
    with pytest.raises(ConfigError, match="DASHSCOPE_API_KEY"):
        await make_qwen(client).extract(video, None, None)


async def test_qwen_server_error_maps_to_extraction_failed(video: Path):
    client = StubHttpClient(response=error_response(500, "internal_error"))
    with pytest.raises(ExtractionFailedError):
        await make_qwen(client).extract(video, None, None)


async def test_qwen_transport_error_leaks_untyped(video: Path):
    """httpx transport failures deliberately leak — the worker fail-closes
    them (terminal + attempt ledgered), same as the Gemini adapter."""
    client = StubHttpClient(error=httpx.ConnectError("connection refused"))
    with pytest.raises(httpx.ConnectError):
        await make_qwen(client).extract(video, None, None)


# ── parse failures (raw preserved, usage carried) ────────────────────────────


async def test_qwen_non_json_output_preserves_raw_and_carries_usage(video: Path):
    raw = "Sure! Here is the recipe: 麻婆豆腐..."
    client = StubHttpClient(response=chat_response(raw, USAGE))
    with pytest.raises(ExtractionFailedError) as exc_info:
        await make_qwen(client).extract(video, None, None)
    assert exc_info.value.raw_text == raw
    assert "麻婆豆腐" in str(exc_info.value)
    assert exc_info.value.usage is not None
    assert exc_info.value.usage.tokens_in == 2509  # billed tokens reach the ledger


async def test_qwen_non_array_json_raises_extraction_failed_preserving_raw(video: Path):
    raw = json.dumps({"dish_name": {"en": "solo", "original": "单"}})
    client = StubHttpClient(response=chat_response(raw, USAGE))
    with pytest.raises(ExtractionFailedError) as exc_info:
        await make_qwen(client).extract(video, None, None)
    assert exc_info.value.raw_text == raw


async def test_qwen_missing_choices_is_extraction_failed_with_usage(video: Path):
    client = StubHttpClient(response=httpx.Response(200, json={"usage": USAGE}))
    with pytest.raises(ExtractionFailedError) as exc_info:
        await make_qwen(client).extract(video, None, None)
    assert exc_info.value.usage is not None


async def test_qwen_non_json_200_body_is_extraction_failed(video: Path):
    client = StubHttpClient(response=httpx.Response(200, text="<html>gateway</html>"))
    with pytest.raises(ExtractionFailedError):
        await make_qwen(client).extract(video, None, None)


# ── the size guard (deterministic — must not burn paid retries) ──────────────


async def test_qwen_oversized_video_refused_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from chefclaw.extractors import qwen as qwen_module

    monkeypatch.setattr(qwen_module, "_MAX_VIDEO_BYTES", 10)
    big = tmp_path / "big.mp4"
    big.write_bytes(b"x" * 11)
    client = StubHttpClient()
    with pytest.raises(ExtractionFailedError) as exc_info:
        await make_qwen(client).extract(big, None, None)
    assert exc_info.value.retryable is False  # deterministic ⇒ terminal
    assert client.calls == []  # refused BEFORE any network/paid call
