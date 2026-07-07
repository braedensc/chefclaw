"""Cover catalog + deterministic sprite assignment (V2-F).

No DB, no network — pure logic over the packaged catalog. The drift test keeps
the backend catalog byte-identical to the canonical frontend one (the openapi.json
discipline, applied to the cover catalog).
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest

from chefclaw import covers


def test_catalog_loads_and_includes_the_fallback() -> None:
    ids = covers.catalog_ids()
    assert len(ids) >= 270  # 274 at authoring; grows via the gardener
    assert covers.UNKNOWN_SPRITE_ID in ids
    assert "red-braised-pork" in ids


def test_menu_excludes_the_fallback_and_lists_every_other_id() -> None:
    menu = covers.catalog_menu()
    lines = menu.splitlines()
    # One line per sprite EXCEPT unknown-dish (the fallback the model must never pick).
    assert len(lines) == len(covers.catalog_ids()) - 1
    assert covers.UNKNOWN_SPRITE_ID not in menu
    # Every menu line leads with a real id.
    ids = covers.catalog_ids()
    assert all(line.split(" | ", 1)[0] in ids for line in lines)


@pytest.mark.parametrize(
    ("dish_en", "dish_zh", "cuisine", "tags", "expected"),
    [
        ("Red-braised pork belly", "红烧肉", "Chinese", ("braise", "pork"), "red-braised-pork"),
        ("Margherita Pizza", "玛格丽特披萨", "Italian", ("pizza",), "margherita-pizza"),
    ],
)
def test_match_sprite_finds_the_obvious_dish(
    dish_en: str, dish_zh: str, cuisine: str, tags: tuple[str, ...], expected: str
) -> None:
    best, confidence = covers.match_sprite(
        dish_name_en=dish_en, dish_name_original=dish_zh, cuisine_type=cuisine, tags=tags
    )
    assert best == expected
    assert confidence >= covers._MATCH_THRESHOLD


def test_match_sprite_returns_none_when_nothing_overlaps() -> None:
    best, confidence = covers.match_sprite(
        dish_name_en="Zqxrb Flooble", dish_name_original=None, cuisine_type=None, tags=()
    )
    assert best is None
    assert confidence == 0.0


def test_match_sprite_never_returns_the_fallback() -> None:
    # unknown-dish is only ever the explicit fallback, never a match candidate.
    best, _c = covers.match_sprite(
        dish_name_en="unknown dish cloche",
        dish_name_original=None,
        cuisine_type=None,
        tags=("unknown", "dish"),
    )
    assert best != covers.UNKNOWN_SPRITE_ID


def test_valid_model_suggestion_is_trusted_without_a_miss() -> None:
    out = covers.assign_cover_sprite(
        suggested_sprite_id="dongpo-pork",
        dish_name_en="whatever",
        dish_name_original=None,
        cuisine_type=None,
        tags=(),
    )
    assert out.sprite_id == "dongpo-pork"
    assert out.miss is None


def test_unknown_model_id_falls_back_and_logs_the_suggestion() -> None:
    out = covers.assign_cover_sprite(
        suggested_sprite_id="not-a-real-sprite",
        dish_name_en="mystery",
        dish_name_original=None,
        cuisine_type=None,
        tags=(),
    )
    assert out.sprite_id == covers.UNKNOWN_SPRITE_ID
    assert out.miss is not None
    assert out.miss.reason == "unknown_model_id"
    assert out.miss.suggested_sprite_id == "not-a-real-sprite"
    assert out.miss.resolved_sprite_id == covers.UNKNOWN_SPRITE_ID


def test_omitted_suggestion_uses_the_matcher_when_confident() -> None:
    out = covers.assign_cover_sprite(
        suggested_sprite_id=None,
        dish_name_en="Red-braised pork belly",
        dish_name_original="红烧肉",
        cuisine_type="Chinese (Jiangnan)",
        tags=("braise", "pork"),
    )
    assert out.sprite_id == "red-braised-pork"
    assert out.miss is None


def test_no_match_falls_back_with_a_no_match_miss() -> None:
    out = covers.assign_cover_sprite(
        suggested_sprite_id=None,
        dish_name_en="Zqxrb Flooble",
        dish_name_original=None,
        cuisine_type=None,
        tags=(),
    )
    assert out.sprite_id == covers.UNKNOWN_SPRITE_ID
    assert out.miss is not None
    assert out.miss.reason == "no_match"
    assert out.miss.suggested_sprite_id is None
    assert out.miss.score is None


def test_backend_catalog_is_byte_identical_to_the_frontend_source() -> None:
    """The backend catalog is a derived copy of the canonical frontend one
    (frontend/src/covers/catalog.json). Keep them in lockstep — same discipline
    as the openapi.json drift job. If this fails, re-copy:
        cp frontend/src/covers/catalog.json backend/src/chefclaw/covers/catalog.json
    """
    backend_bytes = (
        resources.files("chefclaw.covers").joinpath("catalog.json").read_bytes()
    )
    repo_root = Path(__file__).resolve().parents[2]
    frontend_catalog = repo_root / "frontend" / "src" / "covers" / "catalog.json"
    if not frontend_catalog.is_file():
        pytest.skip("frontend catalog not present (backend-only checkout)")
    assert backend_bytes == frontend_catalog.read_bytes(), (
        "backend covers/catalog.json has drifted from the frontend source — re-copy it"
    )
