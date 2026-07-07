"""Illustration persistence helpers — the file-side of generated dish covers.

The card cover is a GENERATED cartoon illustration (V2-E, 2026-07-06), not a
video keyframe. The MODEL side lives behind the ``ImageGeneratorAdapter`` seam
(chefclaw/images/) — config-selected, fake by default. This module owns the
FILE side: where an illustration lands and how bytes get written, so the worker
stays about orchestration (budget → generate → persist → ledger).

Unlike the old ffmpeg cover path, illustrations do NOT depend on a retained
source video — they are generated from text — so nothing here touches the
video archive. One illustration per recipe (dish_index), written under
``{media_dir}/{platform}/{canonical_id}/illustration-{dish_index}.jpg``.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["illustration_path", "write_illustration"]

_ILLUSTRATION_SUFFIX = ".jpg"


def illustration_path(media_root: Path, platform: str, canonical_id: str, dish_index: int) -> Path:
    """The on-disk path for one recipe's illustration (one per dish_index)."""
    return (
        media_root
        / platform
        / canonical_id
        / f"illustration-{dish_index}{_ILLUSTRATION_SUFFIX}"
    )


def write_illustration(out_path: Path, image_bytes: bytes) -> str | None:
    """Write illustration bytes to disk, returning the path string on success.

    STRICTLY BEST-EFFORT: an OS error (unwritable dir, disk full) logs and
    returns ``None`` — the caller leaves image_url NULL and the recipe store is
    never affected. Empty bytes are treated as a miss (never write a 0-byte
    file that the /image route would then 404 on anyway)."""
    if not image_bytes:
        logger.info("no illustration bytes to write for %s", out_path.name)
        return None
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(image_bytes)
    except OSError:
        logger.warning("could not write illustration %s", out_path, exc_info=True)
        return None
    return str(out_path)
