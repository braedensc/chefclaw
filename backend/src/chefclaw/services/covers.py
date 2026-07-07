"""Poster keyframe ("cover") generation — ffmpeg/ffprobe behind a tiny seam.

One cover per dish: dish *i* of *N* takes the frame at ``duration * (i+1)/(N+1)``
so sibling covers from a multi-dish video spread across it instead of all
showing the same opening shot. Duration comes from ffprobe; when it can't be
read the seek falls back to ``3s + 2s * dish_index`` so siblings still differ
(a seek past EOF just fails that frame — None, acceptable).

STRICTLY BEST-EFFORT: every failure (missing binary, nonzero exit, timeout,
unreadable/tiny file) logs and yields ``None`` for that dish — cover
generation must never fail or delay a job's store. The async entrypoint is
the production default for the :data:`CoverGenerator` seam the worker takes
as an injectable collaborator, so CI-tier tests never shell out to ffmpeg.
"""

import asyncio
import logging
import subprocess
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["CoverGenerator", "archived_video_path", "cover_frames", "generate_covers"]

# (video_path, target_dir, frames) -> {dish_index: cover path | None}.
# frames pairs each dish_index with its 0..1 position in the video; each
# produced file lands at target_dir/cover-<dish_index>.jpg. The pairing lets
# the backfill regenerate ONLY missing dishes at their true full-group spread.
CoverGenerator = Callable[
    [Path, Path, Sequence[tuple[int, float]]], Awaitable[dict[int, str | None]]
]

_SUBPROCESS_TIMEOUT_SECONDS = 30.0
# When ffprobe can't read a duration: stagger per dish so siblings differ.
_FALLBACK_SEEK_SECONDS = 3.0
_FALLBACK_SEEK_STEP_SECONDS = 2.0
# 960px wide is plenty for a library card; -2 keeps the encoder-required even
# height; -q:v 3 is visually clean JPEG at a fraction of the frame size.
_FFMPEG_ARGS = ("-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "3")
# Containers the retained archive may hold (yt-dlp / sidecar output).
_VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".mkv", ".webm", ".flv", ".ts"})


def cover_frames(
    dish_count: int, indices: Sequence[int] | None = None
) -> list[tuple[int, float]]:
    """(dish_index, fraction) pairs: dish i of N sits at (i+1)/(N+1) — spread,
    never the exact start/end. ``indices`` narrows to a subset (the backfill
    regenerates only the MISSING dishes) while ``dish_count`` stays the TRUE
    group size so the spread matches the covers that already exist."""
    if indices is None:
        indices = range(dish_count)
    return [(index, (index + 1) / (dish_count + 1)) for index in indices]


def archived_video_path(media_dir: Path) -> Path | None:
    """The retained video in a {platform}/{canonical_id} archive dir, or None.
    Largest candidate wins — extras (note images, covers) are small."""
    try:
        candidates = [
            path
            for path in media_dir.iterdir()
            if path.is_file() and path.suffix.lower() in _VIDEO_SUFFIXES
        ]
        return max(candidates, key=lambda path: path.stat().st_size, default=None)
    except OSError:
        return None


def _probe_duration(video_path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                str(video_path),
            ],
            capture_output=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        duration = float(result.stdout.decode("utf-8", "replace").strip())
    except Exception:
        return None
    return duration if duration > 0 else None


def _extract_frame(video_path: Path, timestamp: float, out_path: Path) -> bool:
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", f"{timestamp:.3f}",
                "-i", str(video_path),
                *_FFMPEG_ARGS,
                str(out_path),
            ],
            capture_output=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except Exception:
        return False
    # ffmpeg can report success yet write nothing (seek past EOF on a broken
    # file): require real bytes on disk before claiming a cover exists.
    return result.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0


def _generate_covers_sync(
    video_path: Path, target_dir: Path, frames: Sequence[tuple[int, float]]
) -> dict[int, str | None]:
    covers: dict[int, str | None] = {dish_index: None for dish_index, _ in frames}
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("cover generation skipped — cannot create %s", target_dir)
        return covers
    duration = _probe_duration(video_path)
    for dish_index, fraction in frames:
        out_path = target_dir / f"cover-{dish_index}.jpg"
        if duration is not None:
            timestamp = duration * fraction
        else:
            # Unknown duration: stagger per dish so siblings still differ; a
            # too-long seek just fails that frame (None, acceptable).
            timestamp = _FALLBACK_SEEK_SECONDS + _FALLBACK_SEEK_STEP_SECONDS * dish_index
        if _extract_frame(video_path, timestamp, out_path):
            covers[dish_index] = str(out_path)
        else:
            logger.info(
                "no cover for %s dish %d (ffmpeg failed)", video_path.name, dish_index
            )
    return covers


async def generate_covers(
    video_path: Path, target_dir: Path, frames: Sequence[tuple[int, float]]
) -> dict[int, str | None]:
    """The production :data:`CoverGenerator`: subprocess work off the event
    loop (the same to_thread pattern as the source adapters). Never raises."""
    try:
        return await asyncio.to_thread(
            _generate_covers_sync, video_path, target_dir, list(frames)
        )
    except Exception:
        logger.warning("cover generation failed for %s", video_path, exc_info=True)
        return {dish_index: None for dish_index, _ in frames}
