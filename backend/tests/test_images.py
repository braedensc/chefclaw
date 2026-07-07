"""ImageGeneratorAdapter tests — CI tier: no network, no spend.

Covers the config-selected fail-closed selection (mirrors the extractor seam),
the fake generator, and build_illustration_prompt's Hard-Rule-7 posture (text
fields only — never a verbatim quantity, never a frame)."""

from decimal import Decimal

import pytest

from chefclaw.config import Settings
from chefclaw.errors import ConfigError
from chefclaw.extractors.fake import default_dish
from chefclaw.images import (
    STYLE_PROMPT_V1,
    STYLE_VERSION,
    ImageResult,
    build_illustration_prompt,
    get_image_generator,
    image_model_id,
)
from chefclaw.images.fake import FakeImageGenerator


def make_settings(**overrides) -> Settings:
    defaults = dict(chefclaw_api_token="t", chefclaw_image_generator="fake")
    defaults.update(overrides)
    return Settings(**defaults)


# ─── get_image_generator: fail-closed selection ──────────────────────────────


def test_default_selects_fake() -> None:
    gen = get_image_generator(make_settings())
    assert isinstance(gen, FakeImageGenerator)


def test_gemini_without_key_is_config_error() -> None:
    """Fail-closed: gemini selected but no key ⇒ ConfigError BEFORE any call."""
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        get_image_generator(make_settings(chefclaw_image_generator="gemini", gemini_api_key=""))


def test_gemini_with_key_constructs(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a key, the gemini adapter constructs (no network at construction)."""
    # A dummy client so no real genai.Client is built.
    from chefclaw.images import gemini as gemini_module

    class DummyClient:
        pass

    monkeypatch.setattr(gemini_module.genai, "Client", lambda **_kw: DummyClient())
    gen = get_image_generator(
        make_settings(chefclaw_image_generator="gemini", gemini_api_key="sk-test")
    )
    assert isinstance(gen, gemini_module.GeminiImageGenerator)


def test_unknown_generator_fails_closed() -> None:
    with pytest.raises(ConfigError):
        get_image_generator(make_settings(chefclaw_image_generator="midjourney"))


def test_image_model_id_readout() -> None:
    assert image_model_id(make_settings()) == "fake-image"
    assert (
        image_model_id(make_settings(chefclaw_image_generator="gemini"))
        == "gemini-3.1-flash-image"
    )


# ─── FakeImageGenerator ──────────────────────────────────────────────────────


async def test_fake_generator_returns_placeholder_bytes() -> None:
    result = await FakeImageGenerator().generate("a dish")
    assert isinstance(result, ImageResult)
    assert result.model_id == "fake-image"
    assert result.image_bytes  # some real bytes on disk
    assert result.cost_usd == Decimal("0")


async def test_fake_generator_records_calls_and_can_fail() -> None:
    gen = FakeImageGenerator()
    await gen.generate("prompt one")
    assert gen.calls[0].prompt == "prompt one"

    boom = FakeImageGenerator(failure=RuntimeError("kaboom"))
    with pytest.raises(RuntimeError, match="kaboom"):
        await boom.generate("x")


# ─── build_illustration_prompt: Hard Rule 7 — text fields only ───────────────


def test_prompt_uses_dish_name_and_ingredient_names() -> None:
    prompt = build_illustration_prompt(default_dish())
    assert "Red-braised pork belly" in prompt  # dish name (en)
    assert "红烧肉" in prompt  # the original name (also text)
    assert "pork belly" in prompt  # an ingredient NAME
    assert STYLE_PROMPT_V1 in prompt  # the versioned style block is prepended


def test_prompt_never_contains_verbatim_quantities() -> None:
    """The default dish has "500克" / "两大勺" / "适量" quantity raw_text — none
    of those may reach the image model (never quantities, never a frame)."""
    prompt = build_illustration_prompt(default_dish())
    for quantity in ("500克", "两大勺", "适量", "500"):
        assert quantity not in prompt


def test_prompt_falls_back_gracefully_on_sparse_document() -> None:
    # Only a name, no cuisine/ingredients — must still produce a usable prompt.
    prompt = build_illustration_prompt({"dish_name": {"en": "Mystery dish"}})
    assert "Mystery dish" in prompt
    assert STYLE_PROMPT_V1 in prompt


def test_style_version_is_stable() -> None:
    assert STYLE_VERSION == "cartoon-v1"
