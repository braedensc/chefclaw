"""Finished-dish beauty-shot frame capture (V2-F private real-frame layer).

ffmpeg (already in the image — it merges DASH streams) grabs ONE frame from the
still-in-scratch source video at the Gemini-returned beauty-shot timestamp
(heuristic ~90%-through fallback), and only that JPEG is kept — the video is
still discarded (``MEDIA_RETENTION=discard``). Strictly BEST-EFFORT: any failure
leaves ``image_url`` NULL and the recipe reads as sprite-only.

Two independent gates keep this off by default and off any ungranted viewer,
enforced UPSTREAM of this module: capture runs only in sprite mode with the
global ``CHEFCLAW_REAL_COVERS`` switch on, and SERVING is additionally gated per
user (``users.real_covers_enabled``). This module only knows how to pick a
timestamp and grab a frame — the worker owns the gating.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["FRAME_STYLE_VERSION", "frame_path", "grab_frame", "resolve_timestamp"]

# The "style version" stamped on a real-frame cover (mirrors STYLE_VERSION for
# generated illustrations) so a recipe records what produced its image_url.
FRAME_STYLE_VERSION = "video-frame-v1"

_FRAME_SUFFIX = ".jpg"
# ffmpeg for a single frame is near-instant; a generous ceiling guards a wedged
# process without blocking the serial worker (the frame is best-effort anyway).
_FRAME_GRAB_TIMEOUT_SECONDS = 30.0
# Fraction-through fallback when the model gave no usable timestamp — a finished
# dish is almost always shown near the very end of a cooking video.
_HEURISTIC_FRACTION = 0.9


def frame_path(
    media_root: Path,
    owner_id: uuid.UUID,
    platform: str,
    canonical_id: str,
    dish_index: int,
) -> Path:
    """The on-disk path for one recipe's captured frame (one per dish_index),
    OWNER-SCOPED (M2). Distinct filename from the generated illustration
    (``illustration-*.jpg``) so the two cover sources never collide."""
    return (
        media_root
        / str(owner_id)
        / platform
        / canonical_id
        / f"frame-{dish_index}{_FRAME_SUFFIX}"
    )


def resolve_timestamp(
    model_timestamp: float | None, duration_seconds: int | float | None
) -> float | None:
    """Pick the seconds offset to grab.

    A model-supplied timestamp wins when it is sane (non-negative, and within the
    known duration); otherwise fall back to ~90% through the (known) duration.
    Returns ``None`` when neither a usable timestamp nor a duration is available
    — the caller then skips capture rather than grab a blind frame."""
    if duration_seconds is not None and duration_seconds > 0:
        if model_timestamp is not None and 0.0 <= model_timestamp <= duration_seconds:
            return float(model_timestamp)
        return round(_HEURISTIC_FRACTION * float(duration_seconds), 3)
    if model_timestamp is not None and model_timestamp >= 0.0:
        return float(model_timestamp)
    return None


async def grab_frame(video_path: Path, timestamp: float, out_path: Path) -> str | None:
    """Grab one JPEG frame at ``timestamp`` seconds via ffmpeg.

    STRICTLY BEST-EFFORT: a missing video, an ffmpeg error, a timeout, or a
    zero-byte result all log and return ``None`` (the caller leaves image_url
    NULL). Never raises for a capture failure — only ``CancelledError`` (worker
    shutdown) propagates."""
    if not video_path.is_file():
        return None
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("frame capture: cannot create %s", out_path.parent, exc_info=True)
        return None
    # -ss before -i seeks fast (keyframe-accurate is fine for a thumbnail);
    # -frames:v 1 grabs a single frame; -q:v 3 is high-quality JPEG.
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(out_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            returncode = await asyncio.wait_for(proc.wait(), _FRAME_GRAB_TIMEOUT_SECONDS)
        except TimeoutError:
            proc.kill()
            logger.warning("frame capture timed out for %s", video_path.name)
            return None
    except asyncio.CancelledError:
        raise
    except (OSError, ValueError):
        logger.warning("frame capture failed to launch ffmpeg", exc_info=True)
        return None
    if returncode != 0:
        logger.warning("frame capture: ffmpeg exited %s for %s", returncode, video_path.name)
        return None
    try:
        if not out_path.is_file() or out_path.stat().st_size == 0:
            return None
    except OSError:
        return None
    return str(out_path)
