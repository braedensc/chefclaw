"""Unit tests for the recipe library service's pure helpers — no database.

The estimate-merge posture (owner corrections re-flag the ``estimated`` column
``source="user"``, taking precedence over the model's derivation) lives in the
pure :func:`_merge_user_estimate`, so it is exercised here in the CI tier; the
full patch round-trip through Postgres is a golden-tier test (test_worker_db)."""

from chefclaw.services.recipes import _UNSET, _merge_user_estimate


def test_merge_flags_source_user_and_overlays_provided_level() -> None:
    """A single corrected level rebuilds the object as owner-authored; the
    untouched level keeps its derived value."""
    current = {"spiciness_level": 1, "difficulty_level": 1, "source": "derived"}
    merged = _merge_user_estimate(
        current, spiciness_level=3, difficulty_level=_UNSET
    )
    assert merged == {"spiciness_level": 3, "difficulty_level": 1, "source": "user"}


def test_merge_from_null_column_starts_from_none() -> None:
    """No prior estimate (null column) ⇒ the unsent level is None, not invented."""
    merged = _merge_user_estimate(None, spiciness_level=2, difficulty_level=_UNSET)
    assert merged == {"spiciness_level": 2, "difficulty_level": None, "source": "user"}


def test_merge_can_set_both_levels() -> None:
    merged = _merge_user_estimate(None, spiciness_level=0, difficulty_level=3)
    assert merged == {"spiciness_level": 0, "difficulty_level": 3, "source": "user"}


def test_merge_clearing_one_level_keeps_object_owner_authored() -> None:
    """Clearing a level (explicit None) is an owner decision — the object stays,
    flagged 'user' so a future re-derivation must not re-fill it."""
    current = {"spiciness_level": 2, "difficulty_level": 2, "source": "derived"}
    merged = _merge_user_estimate(
        current, spiciness_level=None, difficulty_level=_UNSET
    )
    assert merged == {"spiciness_level": None, "difficulty_level": 2, "source": "user"}


def test_merge_clearing_both_levels_still_records_user_provenance() -> None:
    """Even an all-null result is retained (not collapsed to a null column): the
    owner said 'no estimate', and the 'user' flag must survive re-derivation."""
    current = {"spiciness_level": 1, "difficulty_level": 1, "source": "derived"}
    merged = _merge_user_estimate(
        current, spiciness_level=None, difficulty_level=None
    )
    assert merged == {
        "spiciness_level": None,
        "difficulty_level": None,
        "source": "user",
    }


def test_merge_overwrites_a_prior_user_source() -> None:
    """A second correction on an already-user object stays 'user'."""
    current = {"spiciness_level": 3, "difficulty_level": None, "source": "user"}
    merged = _merge_user_estimate(
        current, spiciness_level=_UNSET, difficulty_level=2
    )
    assert merged == {"spiciness_level": 3, "difficulty_level": 2, "source": "user"}
