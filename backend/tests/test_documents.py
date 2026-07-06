"""Tests for the recipe document schema (documents.py) — the gate every
stored recipe passes through. Fixtures are realistic public-cooking-video
style content; NO network, NO database.

The load-bearing assertions: verbatim capture is preserved untouched
(Hard Rule 7), fabrication-shaped coercions are rejected, and provenance
is pipeline-owned.
"""

import copy

import pytest
from pydantic import ValidationError

from chefclaw.documents import (
    BilingualText,
    Quantity,
    RecipeDocument,
    SourceInfo,
    validate_document,
    validate_extraction,
)
from chefclaw.errors import ChefclawError, ValidationFailedError

# ---------------------------------------------------------------------------
# Fixtures — public-video-style bilingual content, built fresh per test so
# mutation checks are meaningful.
# ---------------------------------------------------------------------------

BILI_SOURCE = {
    "platform": "bilibili",
    "url": "https://www.bilibili.com/video/BV1xx411c7mD",
    "creator": "老饭骨",
    "video_duration_seconds": 512,
}


def make_hongshaorou() -> dict:
    """A single-dish document: 红烧肉 (red-braised pork belly)."""
    return {
        "dish_name": {"en": "Red-braised pork belly", "original": "红烧肉"},
        "cuisine_type": "本帮菜",
        "difficulty": "medium",
        "total_time_minutes": 90,
        "servings": None,  # host never says — stays None, NEVER guessed
        "ingredients": [
            {
                "raw_text": "五花肉500g",
                "name": {"en": "pork belly", "original": "五花肉"},
                "quantity": {
                    "raw_text": "500g",
                    "value": 500.0,
                    "unit": "g",
                    "unit_type": "mass",
                },
                "quantity_grams_stated": 500.0,  # host explicitly said 500g
                "prep_state": "raw",
                "notes": "切成麻将块 (cut into mahjong-sized cubes)",
                "nutrition_ref": None,
            },
            {
                "raw_text": "冰糖两大勺",
                "name": {"en": "rock sugar", "original": "冰糖"},
                "quantity": {
                    "raw_text": "两大勺",
                    "value": 2.0,
                    "unit": "大勺",
                    "unit_type": "volume",
                },
                "quantity_grams_stated": None,  # NOT stated as a weight — stays None
                "prep_state": None,
                "notes": None,
                "nutrition_ref": None,
            },
            {
                "raw_text": "盐适量",
                "name": {"en": "salt", "original": "盐"},
                "quantity": {
                    "raw_text": "适量",
                    "value": None,
                    "unit": None,
                    "unit_type": "approx",
                },
                "quantity_grams_stated": None,
                "prep_state": None,
                "notes": None,
                "nutrition_ref": None,
            },
        ],
        "equipment": ["炒锅 (wok)", "砂锅 (clay pot)"],
        "steps": [
            {
                "step_number": 1,
                "instruction": "五花肉冷水下锅焯水，捞出洗净。Blanch from cold water, rinse.",
                "duration": "约5分钟",
                "visual_cues": "浮沫变多后捞出 (remove once scum rises)",
                "technique_notes": None,
            },
            {
                "step_number": 2,
                "instruction": "小火炒糖色至琥珀色。Melt the rock sugar over low heat to amber.",
                "duration": None,
                "visual_cues": "呈琥珀色冒小泡 (amber with small bubbles)",
                "technique_notes": "全程小火，糖色发黑就苦了 (low heat — burnt sugar is bitter)",
            },
            {
                "step_number": 3,
                "instruction": "下肉块翻炒上色，加热水没过肉，小火炖至软糯。Coat and braise.",
                "duration": "45分钟",
                "visual_cues": "汤汁收浓挂勺 (sauce reduced enough to coat a spoon)",
                "technique_notes": None,
            },
        ],
        "tips": ["加热水不加冷水，肉不容易柴 (hot water keeps the pork tender)"],
        "source": dict(BILI_SOURCE),
    }


def make_liangban_huanggua() -> dict:
    """Second dish for multi-dish extractions: 凉拌黄瓜 (smashed cucumber salad)."""
    return {
        "dish_name": {"en": "Smashed cucumber salad", "original": "凉拌黄瓜"},
        "cuisine_type": None,
        "difficulty": "easy",
        "total_time_minutes": 10,
        "servings": 2,
        "ingredients": [
            {
                "raw_text": "黄瓜两根",
                "name": {"en": "cucumber", "original": "黄瓜"},
                "quantity": {
                    "raw_text": "两根",
                    "value": 2.0,
                    "unit": "根",
                    "unit_type": "count",
                },
                "quantity_grams_stated": None,
                "prep_state": "fresh",
                "notes": "拍碎 (smashed)",
                "nutrition_ref": None,
            },
            {
                "raw_text": "蒜末适量",
                "name": {"en": "minced garlic", "original": "蒜末"},
                "quantity": {
                    "raw_text": "适量",
                    "value": None,
                    "unit": None,
                    "unit_type": "approx",
                },
                "quantity_grams_stated": None,
                "prep_state": None,
                "notes": None,
                "nutrition_ref": None,
            },
        ],
        "equipment": [],
        "steps": [
            {
                "step_number": 1,
                "instruction": "黄瓜拍碎切段，加盐腌10分钟出水。Smash cucumbers, salt 10 minutes.",
                "duration": "10分钟",
                "visual_cues": None,
                "technique_notes": None,
            },
            {
                "step_number": 2,
                "instruction": "倒掉水，拌入蒜末、醋、香油。Drain, dress with garlic and vinegar.",
                "duration": None,
                "visual_cues": None,
                "technique_notes": None,
            },
        ],
        "tips": [],
        "source": dict(BILI_SOURCE),
    }


def make_source(**overrides) -> SourceInfo:
    return SourceInfo.model_validate({**BILI_SOURCE, **overrides})


# ---------------------------------------------------------------------------
# Valid documents
# ---------------------------------------------------------------------------


def test_valid_single_dish_document() -> None:
    doc = validate_document(make_hongshaorou())
    assert isinstance(doc, RecipeDocument)
    assert doc.dish_name.original == "红烧肉"
    assert doc.dish_name.en == "Red-braised pork belly"
    assert doc.servings is None  # unstated stays unstated
    assert len(doc.ingredients) == 3
    assert doc.ingredients[0].quantity_grams_stated == 500.0
    assert doc.ingredients[1].quantity_grams_stated is None
    assert [step.step_number for step in doc.steps] == [1, 2, 3]
    assert doc.source.platform == "bilibili"


def test_valid_multi_dish_extraction() -> None:
    source = make_source()
    docs = validate_extraction([make_hongshaorou(), make_liangban_huanggua()], source)
    assert len(docs) == 2
    assert docs[0].dish_name.original == "红烧肉"
    assert docs[1].dish_name.original == "凉拌黄瓜"
    for doc in docs:
        assert doc.source == source


def test_local_platform_accepted_and_unknown_platform_rejected() -> None:
    # 'local' is the Tier-2 file-upload floor (plan §16.10).
    raw = make_hongshaorou()
    raw["source"] = {
        "platform": "local",
        "url": "file:///uploads/hongshaorou.mp4",
        "creator": None,
        "video_duration_seconds": None,
    }
    assert validate_document(raw).source.platform == "local"

    raw = make_hongshaorou()
    raw["source"]["platform"] = "youtube"
    with pytest.raises(ValidationFailedError):
        validate_document(raw)


def test_bilingual_text_single_side_ok() -> None:
    assert BilingualText.model_validate({"original": "豆瓣酱"}).en is None
    assert BilingualText.model_validate({"en": "doubanjiang"}).original is None


# ---------------------------------------------------------------------------
# 适量 / approx round-trip (Hard Rule 7)
# ---------------------------------------------------------------------------


def test_shiliang_approx_round_trip() -> None:
    raw = make_hongshaorou()
    doc = validate_document(raw)
    salt = doc.ingredients[2]
    assert salt.raw_text == "盐适量"
    assert salt.quantity is not None
    assert salt.quantity.raw_text == "适量"
    assert salt.quantity.value is None
    assert salt.quantity.unit is None
    assert salt.quantity.unit_type == "approx"
    # dump round-trips to exactly the input quantity dict — nothing filled in
    assert doc.model_dump()["ingredients"][2]["quantity"] == raw["ingredients"][2]["quantity"]
    # and the dump re-validates
    assert validate_document(doc.model_dump()) == doc


# ---------------------------------------------------------------------------
# Rejections — schema violations must fail whole, never be repaired
# ---------------------------------------------------------------------------


def _assert_rejected(raw: dict) -> ValidationFailedError:
    with pytest.raises(ValidationFailedError) as exc_info:
        validate_document(raw)
    return exc_info.value


def test_missing_ingredient_raw_text_rejected() -> None:
    raw = make_hongshaorou()
    del raw["ingredients"][0]["raw_text"]
    _assert_rejected(raw)


def test_empty_ingredient_raw_text_rejected() -> None:
    raw = make_hongshaorou()
    raw["ingredients"][0]["raw_text"] = ""
    _assert_rejected(raw)


def test_non_null_nutrition_ref_rejected() -> None:
    # Reserved for pillar 2 — the extractor must never fill it.
    raw = make_hongshaorou()
    raw["ingredients"][0]["nutrition_ref"] = {"source": "fdc", "id": 171401, "confidence": 0.9}
    _assert_rejected(raw)


def test_unknown_extra_fields_rejected() -> None:
    raw = make_hongshaorou()
    raw["estimated_calories"] = 850  # fabrication-shaped extra
    _assert_rejected(raw)

    raw = make_hongshaorou()
    raw["ingredients"][0]["grams_estimated"] = 480  # nested extra
    _assert_rejected(raw)

    raw = make_hongshaorou()
    raw["ingredients"][1]["quantity"]["approx_grams"] = 30
    _assert_rejected(raw)


def test_empty_ingredients_rejected() -> None:
    raw = make_hongshaorou()
    raw["ingredients"] = []
    _assert_rejected(raw)


def test_empty_steps_rejected() -> None:
    raw = make_hongshaorou()
    raw["steps"] = []
    _assert_rejected(raw)


def test_non_ascending_steps_rejected() -> None:
    raw = make_hongshaorou()
    raw["steps"][1]["step_number"] = 3
    raw["steps"][2]["step_number"] = 2  # 1, 3, 2
    _assert_rejected(raw)

    raw = make_hongshaorou()
    raw["steps"][2]["step_number"] = 2  # duplicate: 1, 2, 2
    _assert_rejected(raw)


def test_step_number_below_one_rejected() -> None:
    raw = make_hongshaorou()
    raw["steps"][0]["step_number"] = 0
    _assert_rejected(raw)


def test_both_null_bilingual_text_rejected() -> None:
    raw = make_hongshaorou()
    raw["dish_name"] = {"en": None, "original": None}
    _assert_rejected(raw)


def test_empty_string_bilingual_side_rejected() -> None:
    # "" is an absent name wearing a string — it must not satisfy the
    # at-least-one-side invariant (or be stored as a name at all).
    raw = make_hongshaorou()
    raw["dish_name"] = {"en": "", "original": None}
    _assert_rejected(raw)

    raw = make_hongshaorou()
    raw["ingredients"][0]["name"] = {"en": "", "original": "五花肉"}
    _assert_rejected(raw)

    with pytest.raises(ValidationError):  # direct model use raises pydantic's error
        BilingualText.model_validate({})


# ---------------------------------------------------------------------------
# Coercion contract (documented in the module docstring):
# strings NEVER become numbers, bools NEVER become ints; the one accepted
# lossless coercion is int -> float (JSON `2` == `2.0`).
# ---------------------------------------------------------------------------


def test_string_value_is_not_coerced_to_float() -> None:
    raw = make_hongshaorou()
    raw["ingredients"][1]["quantity"]["value"] = "2"  # must NOT become 2.0
    _assert_rejected(raw)


def test_string_grams_stated_is_not_coerced() -> None:
    raw = make_hongshaorou()
    raw["ingredients"][0]["quantity_grams_stated"] = "500"
    _assert_rejected(raw)


def test_string_ints_are_not_coerced() -> None:
    raw = make_hongshaorou()
    raw["servings"] = "4"
    _assert_rejected(raw)

    raw = make_hongshaorou()
    raw["steps"][0]["step_number"] = "1"
    _assert_rejected(raw)


def test_bool_is_not_coerced_to_int() -> None:
    raw = make_hongshaorou()
    raw["servings"] = True
    _assert_rejected(raw)


def test_lossless_int_to_float_is_the_one_accepted_coercion() -> None:
    # JSON `2` for a float field is the same number as 2.0 — accepted.
    raw = make_hongshaorou()
    raw["ingredients"][1]["quantity"]["value"] = 2  # int, not float
    doc = validate_document(raw)
    value = doc.ingredients[1].quantity.value
    assert isinstance(value, float)
    assert value == 2.0


def test_float_is_not_coerced_to_int() -> None:
    raw = make_hongshaorou()
    raw["total_time_minutes"] = 90.0  # float for an int field — rejected in strict mode
    _assert_rejected(raw)


# ---------------------------------------------------------------------------
# Consistency bounds — impossible values are rejected, never adjusted
# ---------------------------------------------------------------------------


def test_non_positive_quantity_value_rejected() -> None:
    for bad in (0, -500.0):
        raw = make_hongshaorou()
        raw["ingredients"][0]["quantity"]["value"] = bad
        _assert_rejected(raw)


def test_non_positive_grams_stated_rejected() -> None:
    for bad in (0, -500.0):
        raw = make_hongshaorou()
        raw["ingredients"][0]["quantity_grams_stated"] = bad
        _assert_rejected(raw)


def test_non_positive_servings_and_time_rejected() -> None:
    for field, bad in (("servings", 0), ("servings", -2), ("total_time_minutes", 0)):
        raw = make_hongshaorou()
        raw[field] = bad
        _assert_rejected(raw)


def test_negative_video_duration_rejected() -> None:
    raw = make_hongshaorou()
    raw["source"]["video_duration_seconds"] = -1
    _assert_rejected(raw)


# ---------------------------------------------------------------------------
# Error contract
# ---------------------------------------------------------------------------


def test_error_preserves_raw_output_identity_and_type() -> None:
    raw = make_hongshaorou()
    raw["ingredients"] = []
    err = _assert_rejected(raw)
    assert err.raw_output is raw  # the exact object, for debugging
    assert isinstance(err, ChefclawError)
    assert err.error_type == "validation_failed"
    assert err.retryable is False
    assert "validation" in str(err)


def test_non_dict_input_raises_typed_error() -> None:
    with pytest.raises(ValidationFailedError) as exc_info:
        validate_document(["not", "a", "dict"])  # type: ignore[arg-type]
    assert exc_info.value.raw_output == ["not", "a", "dict"]


# ---------------------------------------------------------------------------
# Never mutates — raw in == raw out for verbatim fields
# ---------------------------------------------------------------------------


def test_validate_document_never_mutates_input() -> None:
    raw = make_hongshaorou()
    snapshot = copy.deepcopy(raw)
    doc = validate_document(raw)
    assert raw == snapshot  # input untouched
    # verbatim fields come out exactly as they went in
    for i, ingredient in enumerate(raw["ingredients"]):
        assert doc.ingredients[i].raw_text == ingredient["raw_text"]
        if ingredient["quantity"] is not None:
            assert doc.ingredients[i].quantity.raw_text == ingredient["quantity"]["raw_text"]
            assert doc.ingredients[i].quantity.value == ingredient["quantity"]["value"]
            assert doc.ingredients[i].quantity.unit == ingredient["quantity"]["unit"]


def test_failed_validation_does_not_mutate_input() -> None:
    raw = make_hongshaorou()
    raw["ingredients"][2]["quantity"]["value"] = "适量"  # invalid: str for float
    snapshot = copy.deepcopy(raw)
    _assert_rejected(raw)
    assert raw == snapshot


# ---------------------------------------------------------------------------
# validate_extraction — pipeline-owned provenance
# ---------------------------------------------------------------------------


def test_validate_extraction_overrides_model_supplied_source() -> None:
    dish = make_hongshaorou()
    # the model lies about provenance — it must be discarded
    dish["source"] = {
        "platform": "rednote",
        "url": "https://evil.example/fabricated",
        "creator": "not-the-real-creator",
        "video_duration_seconds": 1,
    }
    source = make_source()
    docs = validate_extraction([dish], source)
    assert docs[0].source == source
    assert docs[0].source.url == BILI_SOURCE["url"]


def test_validate_extraction_injects_source_when_absent() -> None:
    dish = make_hongshaorou()
    del dish["source"]
    source = make_source(platform="rednote", url="https://www.xiaohongshu.com/explore/65f0a1")
    docs = validate_extraction([dish], source)
    assert docs[0].source.platform == "rednote"


def test_validate_extraction_does_not_mutate_inputs() -> None:
    dishes = [make_hongshaorou(), make_liangban_huanggua()]
    del dishes[0]["source"]  # absent on one, present on the other
    snapshot = copy.deepcopy(dishes)
    validate_extraction(dishes, make_source())
    assert dishes == snapshot


def test_validate_extraction_empty_list_rejected() -> None:
    with pytest.raises(ValidationFailedError):
        validate_extraction([], make_source())


def test_validate_extraction_non_dict_dish_rejected() -> None:
    junk = "I could not find a recipe in this video."
    with pytest.raises(ValidationFailedError) as exc_info:
        validate_extraction([junk], make_source())  # type: ignore[list-item]
    assert exc_info.value.raw_output is junk


def test_validate_extraction_error_names_failing_dish() -> None:
    good = make_hongshaorou()
    bad = make_liangban_huanggua()
    bad["ingredients"] = []
    with pytest.raises(ValidationFailedError) as exc_info:
        validate_extraction([good, bad], make_source())
    assert "dish 1" in str(exc_info.value)
    assert exc_info.value.raw_output["dish_name"]["original"] == "凉拌黄瓜"


# ---------------------------------------------------------------------------
# Misc structure
# ---------------------------------------------------------------------------


def test_quantity_is_optional_on_ingredient() -> None:
    raw = make_hongshaorou()
    raw["ingredients"][2]["quantity"] = None
    doc = validate_document(raw)
    assert doc.ingredients[2].quantity is None


def test_optional_document_fields_default_to_none() -> None:
    raw = make_hongshaorou()
    for key in ("cuisine_type", "difficulty", "total_time_minutes", "servings"):
        del raw[key]
    doc = validate_document(raw)
    assert doc.cuisine_type is None
    assert doc.difficulty is None
    assert doc.total_time_minutes is None
    assert doc.servings is None


def test_quantity_model_direct_construction() -> None:
    q = Quantity(raw_text="两大勺", value=2.0, unit="大勺", unit_type="volume")
    assert q.raw_text == "两大勺"
    with pytest.raises(ValidationError):  # pydantic error on bad literal
        Quantity(raw_text="两大勺", unit_type="handfuls")


def test_all_null_quantity_object_canonicalizes_to_none() -> None:
    """The two encodings of "no quantity stated" are the same value — an
    all-null quantity object collapses to None (canonicalization, not repair)."""
    from chefclaw.documents import Ingredient

    ing = Ingredient.model_validate(
        {
            "raw_text": "五花肉",
            "name": {"en": "pork belly", "original": "五花肉"},
            "quantity": {"raw_text": None, "value": None, "unit": None, "unit_type": None},
        }
    )
    assert ing.quantity is None


def test_partially_null_quantity_still_rejected() -> None:
    """A value with no raw_text is inconsistent data, not an absence — reject."""
    import pydantic
    import pytest as _pytest

    from chefclaw.documents import Ingredient

    with _pytest.raises(pydantic.ValidationError):
        Ingredient.model_validate(
            {
                "raw_text": "五花肉",
                "name": {"en": "pork belly", "original": "五花肉"},
                "quantity": {"raw_text": None, "value": 2.0, "unit": None, "unit_type": None},
            }
        )


def test_empty_quantity_dict_still_rejected() -> None:
    """An empty dict is neither encoding of absence — strict schema rejects it
    (missing required raw_text)."""
    import pydantic
    import pytest as _pytest

    from chefclaw.documents import Ingredient

    with _pytest.raises(pydantic.ValidationError):
        Ingredient.model_validate(
            {
                "raw_text": "五花肉",
                "name": {"en": "pork belly", "original": "五花肉"},
                "quantity": {},
            }
        )


def test_null_text_quantity_with_approx_tag_canonicalizes_to_none() -> None:
    """unit_type set on an otherwise-null quantity is a classification of
    absence — same canonicalization applies."""
    from chefclaw.documents import Ingredient

    ing = Ingredient.model_validate(
        {
            "raw_text": "葱花",
            "name": {"en": "scallions", "original": "葱花"},
            "quantity": {"raw_text": None, "value": None, "unit": None, "unit_type": "approx"},
        }
    )
    assert ing.quantity is None


def test_null_text_quantity_with_unit_still_rejected() -> None:
    """A unit without raw_text is data from nowhere — reject."""
    import pydantic
    import pytest as _pytest

    from chefclaw.documents import Ingredient

    with _pytest.raises(pydantic.ValidationError):
        Ingredient.model_validate(
            {
                "raw_text": "葱花",
                "name": {"en": "scallions", "original": "葱花"},
                "quantity": {"raw_text": None, "value": None, "unit": "tbsp", "unit_type": None},
            }
        )
