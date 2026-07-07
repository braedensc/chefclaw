"""Dish-sprite catalog + cover assignment (V2-F).

The 274 original neon-night-market SVG dish sprites live in the FRONTEND
(``frontend/src/covers/``), where they render inline on the card + detail. This
module owns the BACKEND half of the cover system: a byte-identical copy of the
catalog (``catalog.json`` — kept honest by a drift test) used to

1. build the compact catalog menu appended to the extraction prompt,
2. validate the ``cover_sprite_id`` the model picks, and
3. run the **deterministic keyword matcher** — the fallback for a model miss,
   the fake extractor, and the startup backfill.

The matcher is the load-bearing safety net: it is the ONLY assignment path that
does not depend on the model getting the id right, so every recipe always ends
up with a sprite. A confident match wins; otherwise assignment resolves to the
generic ``unknown-dish`` sprite and logs an :class:`AssignmentMiss` (→ the
``cover_misses`` table) for the future cover gardener.

Hard Rule 7 does not apply here — a sprite is a decorative default, not captured
food data. Nothing in this module estimates or fabricates a quantity.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

__all__ = [
    "UNKNOWN_SPRITE_ID",
    "AssignmentMiss",
    "CoverAssignment",
    "assign_cover_sprite",
    "catalog_ids",
    "catalog_menu",
    "load_catalog",
    "match_sprite",
]

# The final-fallback sprite (a generic cloche) — always present in the catalog.
UNKNOWN_SPRITE_ID = "unknown-dish"

# A confident deterministic match must clear this. Confidence is
# ``score / (score + _CONFIDENCE_K)`` (see ``match_sprite``), so 0.5 ⇔ a raw
# score of _CONFIDENCE_K — roughly "one shared category tag plus a little more".
_MATCH_THRESHOLD = 0.5
_CONFIDENCE_K = 3.0

# How many tags per sprite ride into the prompt menu — enough to characterize,
# capped so the menu stays compact (this rides EVERY extraction call).
_MENU_TAGS = 6

_CJK = r"一-鿿"
_CJK_RUN = re.compile(f"[{_CJK}]+")
_EN_WORD = re.compile(r"[a-z0-9]+")
# Common words that carry no dish signal — dropped from EN token sets so a
# shared "with"/"and" never inflates a match.
_STOPWORDS = frozenset(
    {"the", "and", "with", "for", "from", "style", "made", "served", "your", "this"}
)


@dataclass(frozen=True)
class _Sprite:
    """One catalog entry plus its precomputed match tokens."""

    id: str
    name_en: str
    name_zh: str
    tags: tuple[str, ...]
    words: frozenset[str]  # EN tokens (id parts + name_en + tag words + raw tags)
    tag_set: frozenset[str]  # raw tags, for the strong exact-tag signal
    cjk_bigrams: frozenset[str]
    cjk_chars: frozenset[str]


@dataclass(frozen=True)
class AssignmentMiss:
    """A cover-assignment miss — assignment fell back to ``unknown-dish``. The
    worker/backfill attach ``owner_id``/``recipe_id`` and persist it to
    ``cover_misses`` (append-only; the ONLY input the cover gardener consumes)."""

    dish_name_en: str | None
    dish_name_original: str | None
    cuisine_type: str | None
    tags: tuple[str, ...]
    suggested_sprite_id: str | None  # the model's id when it was NOT a known one
    resolved_sprite_id: str
    score: float | None  # best deterministic confidence, None when no candidate
    reason: str  # 'unknown_model_id' | 'low_confidence' | 'no_match'


@dataclass(frozen=True)
class CoverAssignment:
    """The resolved sprite id + an optional miss to log."""

    sprite_id: str
    miss: AssignmentMiss | None


def _en_words(*texts: str | None) -> set[str]:
    words: set[str] = set()
    for text in texts:
        if not text:
            continue
        for tok in _EN_WORD.findall(text.lower()):
            if len(tok) >= 3 and tok not in _STOPWORDS:
                words.add(tok)
    return words


def _cjk_chars(*texts: str | None) -> set[str]:
    chars: set[str] = set()
    for text in texts:
        if not text:
            continue
        for run in _CJK_RUN.findall(text):
            chars.update(run)
    return chars


def _cjk_bigrams(*texts: str | None) -> set[str]:
    bigrams: set[str] = set()
    for text in texts:
        if not text:
            continue
        for run in _CJK_RUN.findall(text):
            for i in range(len(run) - 1):
                bigrams.add(run[i : i + 2])
    return bigrams


@lru_cache(maxsize=1)
def load_catalog() -> tuple[_Sprite, ...]:
    """Parse ``catalog.json`` (packaged beside this module) into sprites with
    precomputed match tokens. Cached process-wide."""
    raw = (
        resources.files("chefclaw.covers")
        .joinpath("catalog.json")
        .read_text(encoding="utf-8")
    )
    entries = json.loads(raw)
    sprites: list[_Sprite] = []
    for entry in entries:
        tags = tuple(str(t) for t in entry.get("tags", []))
        name_en = str(entry.get("name_en") or "")
        name_zh = str(entry.get("name_zh") or "")
        id_parts = str(entry["id"]).replace("-", " ")
        words = frozenset(
            _en_words(id_parts, name_en, *tags) | {t.lower() for t in tags}
        )
        sprites.append(
            _Sprite(
                id=str(entry["id"]),
                name_en=name_en,
                name_zh=name_zh,
                tags=tags,
                words=words,
                tag_set=frozenset(t.lower() for t in tags),
                cjk_bigrams=frozenset(_cjk_bigrams(name_zh, *tags)),
                cjk_chars=frozenset(_cjk_chars(name_zh, *tags)),
            )
        )
    return tuple(sprites)


@lru_cache(maxsize=1)
def catalog_ids() -> frozenset[str]:
    """Every known sprite id (including ``unknown-dish``)."""
    return frozenset(s.id for s in load_catalog())


@lru_cache(maxsize=1)
def catalog_menu() -> str:
    """The compact ``id | name_en | name_zh | tags`` menu appended to the
    extraction prompt so the model picks a VALID id. Excludes ``unknown-dish``
    (the fallback — the model should never pick it; a non-cooking video is an
    empty array, not a cloche)."""
    lines = []
    for sprite in load_catalog():
        if sprite.id == UNKNOWN_SPRITE_ID:
            continue
        tags = ", ".join(sprite.tags[:_MENU_TAGS])
        lines.append(f"{sprite.id} | {sprite.name_en} | {sprite.name_zh} | {tags}")
    return "\n".join(lines)


def match_sprite(
    *,
    dish_name_en: str | None,
    dish_name_original: str | None,
    cuisine_type: str | None,
    tags: tuple[str, ...] | list[str],
) -> tuple[str | None, float]:
    """Deterministic best-fit sprite for a dish's text signals.

    Returns ``(sprite_id, confidence)`` — the highest-scoring sprite and its
    confidence in [0, 1), or ``(None, 0.0)`` when the catalog yields no overlap
    at all. Ties break on the lower id (stable, testable). ``unknown-dish`` is
    never a match candidate — it is only ever the explicit fallback.

    Scoring (higher = stronger, per shared signal): an exact category tag +2, a
    shared EN content word +1, a shared CJK bigram +2, a shared CJK char +0.5.
    Confidence squashes the raw score with ``score / (score + K)`` so it is
    comparable across dishes with different amounts of text.
    """
    query_tags = frozenset(t.lower() for t in tags)
    query_words = _en_words(dish_name_en, cuisine_type, *tags) | query_tags
    query_bigrams = _cjk_bigrams(dish_name_original, *tags)
    query_chars = _cjk_chars(dish_name_original, *tags)

    best_id: str | None = None
    best_score = 0.0
    for sprite in load_catalog():
        if sprite.id == UNKNOWN_SPRITE_ID:
            continue
        score = (
            2.0 * len(query_tags & sprite.tag_set)
            + 1.0 * len(query_words & sprite.words)
            + 2.0 * len(query_bigrams & sprite.cjk_bigrams)
            + 0.5 * len(query_chars & sprite.cjk_chars)
        )
        # Strictly-greater keeps the first (lowest, since the catalog is sorted
        # by id) on ties — deterministic.
        if score > best_score:
            best_score = score
            best_id = sprite.id

    if best_id is None or best_score <= 0.0:
        return None, 0.0
    confidence = best_score / (best_score + _CONFIDENCE_K)
    return best_id, confidence


def assign_cover_sprite(
    *,
    suggested_sprite_id: str | None,
    dish_name_en: str | None,
    dish_name_original: str | None,
    cuisine_type: str | None,
    tags: tuple[str, ...] | list[str],
) -> CoverAssignment:
    """Resolve one recipe's ``cover_sprite_id``.

    Precedence:

    1. **A valid model suggestion wins** — a known catalog id that isn't the
       fallback is trusted as-is (the model watched the video); no miss.
    2. Otherwise the **deterministic matcher** runs; a match above the
       confidence threshold wins (no miss).
    3. Otherwise assignment falls back to ``unknown-dish`` and returns an
       :class:`AssignmentMiss` (``reason`` distinguishes an unknown model id, a
       low-confidence best match, and no candidate at all).
    """
    known = catalog_ids()
    if (
        suggested_sprite_id
        and suggested_sprite_id in known
        and suggested_sprite_id != UNKNOWN_SPRITE_ID
    ):
        return CoverAssignment(suggested_sprite_id, None)

    unknown_model_id = bool(suggested_sprite_id) and suggested_sprite_id not in known
    best_id, confidence = match_sprite(
        dish_name_en=dish_name_en,
        dish_name_original=dish_name_original,
        cuisine_type=cuisine_type,
        tags=tags,
    )
    if best_id is not None and confidence >= _MATCH_THRESHOLD:
        return CoverAssignment(best_id, None)

    if unknown_model_id:
        reason = "unknown_model_id"
    elif best_id is not None:
        reason = "low_confidence"
    else:
        reason = "no_match"
    miss = AssignmentMiss(
        dish_name_en=dish_name_en,
        dish_name_original=dish_name_original,
        cuisine_type=cuisine_type,
        tags=tuple(tags),
        suggested_sprite_id=suggested_sprite_id if unknown_model_id else None,
        resolved_sprite_id=UNKNOWN_SPRITE_ID,
        score=confidence if best_id is not None else None,
        reason=reason,
    )
    return CoverAssignment(UNKNOWN_SPRITE_ID, miss)
