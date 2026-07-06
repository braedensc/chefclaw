"""Poster keyframe ("cover") generation — ffmpeg/ffprobe behind a tiny seam.

One cover per dish: dish *i* of *N* takes the frame at ``duration * (i+1)/(N+1)``
so sibling covers from a multi-dish video spread across it instead of all
showing the same opening shot. Duration comes from ffprobe; when it can't be
read the frame falls back to a fixed 3s seek.

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

__all__ = ["CoverGenerator", "archived_video_path", "cover_fractions", "generate_covers"]

# (video_path, target_dir, fractions) -> per-dish cover paths (None = no
# cover). fractions[i] is dish i's position in the video as a 0..1 fraction;
# the file lands at target_dir/cover-<i>.jpg.
CoverGenerator = Callable[[Path, Path, Sequence[float]], Awaitable[list[str | None]]]

_SUBPROCESS_TIMEOUT_SECONDS = 30.0
_FALLBACK_SEEK_SECONDS = 3.0  # when ffprobe can't read a duration
# 960px wide is plenty for a library card; -2 keeps the encoder-required even
# height; -q:v 3 is visually clean JPEG at a fraction of the frame size.
_FFMPEG_ARGS = ("-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "3")
# Containers the retained archive may hold (yt-dlp / sidecar output).
_VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".mkv", ".webm", ".flv", ".ts"})


def cover_fractions(dish_count: int) -> list[float]:
    """Dish i of N sits at (i+1)/(N+1) — spread, never the exact start/end."""
    return [(index + 1) / (dish_count + 1) for index in range(dish_count)]


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
    video_path: Path, target_dir: Path, fractions: Sequence[float]
) -> list[str | None]:
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("cover generation skipped — cannot create %s", target_dir)
        return [None] * len(fractions)
    duration = _probe_duration(video_path)
    covers: list[str | None] = []
    for index, fraction in enumerate(fractions):
        out_path = target_dir / f"cover-{index}.jpg"
        timestamp = duration * fraction if duration is not None else _FALLBACK_SEEK_SECONDS
        if _extract_frame(video_path, timestamp, out_path):
            covers.append(str(out_path))
        else:
            logger.info("no cover for %s frame %d (ffmpeg failed)", video_path.name, index)
            covers.append(None)
    return covers


async def generate_covers(
    video_path: Path, target_dir: Path, fractions: Sequence[float]
) -> list[str | None]:
    """The production :data:`CoverGenerator`: subprocess work off the event
    loop (the same to_thread pattern as the source adapters). Never raises."""
    try:
        return await asyncio.to_thread(
            _generate_covers_sync, video_path, target_dir, list(fractions)
        )
    except Exception:
        logger.warning("cover generation failed for %s", video_path, exc_info=True)
        return [None] * len(fractions)
