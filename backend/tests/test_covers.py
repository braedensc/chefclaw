"""Cover generation tests — CI tier: subprocess is monkeypatched, so real
ffmpeg/ffprobe are NEVER invoked (the worker/API tiers inject fake generators;
this file exercises the production generator's own logic)."""

from pathlib import Path

import pytest

from chefclaw.services import covers


class FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: bytes = b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = b""


def _run_recorder(calls: list[list[str]], *, probe_stdout: bytes | None, ffmpeg_ok: bool = True):
    """A subprocess.run double: ffprobe answers ``probe_stdout`` (None = exit
    1), ffmpeg writes the output file when ``ffmpeg_ok``."""

    def fake_run(args, capture_output, timeout):
        calls.append([str(a) for a in args])
        if args[0] == "ffprobe":
            if probe_stdout is None:
                return FakeCompleted(returncode=1)
            return FakeCompleted(stdout=probe_stdout)
        if ffmpeg_ok:
            Path(args[-1]).write_bytes(b"fake jpeg bytes")
            return FakeCompleted()
        return FakeCompleted(returncode=1)

    return fake_run


# ─── frame math ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("dish_count", "expected"),
    [
        (1, [(0, 0.5)]),
        (2, [(0, 1 / 3), (1, 2 / 3)]),
        (3, [(0, 0.25), (1, 0.5), (2, 0.75)]),
    ],
)
def test_cover_frames_spread_across_the_video(
    dish_count: int, expected: list[tuple[int, float]]
) -> None:
    frames = covers.cover_frames(dish_count)
    assert [index for index, _ in frames] == [index for index, _ in expected]
    assert [fraction for _, fraction in frames] == pytest.approx(
        [fraction for _, fraction in expected]
    )


def test_cover_frames_subset_keeps_the_full_group_spread() -> None:
    """The backfill's shape: only dish 1 of a 3-dish group is missing — its
    fraction must be the 3-dish spread's 2/4, not a 1-dish 1/2 of a different
    N."""
    assert covers.cover_frames(3, [1]) == [(1, pytest.approx(0.5))]
    assert covers.cover_frames(4, [0, 2]) == [
        (0, pytest.approx(0.2)),
        (2, pytest.approx(0.6)),
    ]


# ─── generate_covers (production generator, subprocess faked) ────────────────


async def test_generate_covers_seeks_at_duration_times_fraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        covers.subprocess, "run", _run_recorder(calls, probe_stdout=b"120.0\n")
    )
    video = tmp_path / "video.mp4"
    video.write_bytes(b"not really a video")
    target_dir = tmp_path / "archive"

    result = await covers.generate_covers(video, target_dir, [(0, 1 / 3), (1, 2 / 3)])

    assert result == {
        0: str(target_dir / "cover-0.jpg"),
        1: str(target_dir / "cover-1.jpg"),
    }
    assert (target_dir / "cover-0.jpg").is_file()
    ffmpeg_calls = [call for call in calls if call[0] == "ffmpeg"]
    seeks = [call[call.index("-ss") + 1] for call in ffmpeg_calls]
    assert seeks == ["40.000", "80.000"]  # 120s * 1/3, 120s * 2/3


async def test_generate_covers_names_files_by_dish_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing-only backfill frame set writes cover-<dish_index>.jpg, never
    positional cover-0 for whatever came first."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        covers.subprocess, "run", _run_recorder(calls, probe_stdout=b"100.0\n")
    )
    video = tmp_path / "video.mp4"
    video.write_bytes(b"not really a video")
    target_dir = tmp_path / "archive"

    result = await covers.generate_covers(video, target_dir, [(2, 0.75)])

    assert result == {2: str(target_dir / "cover-2.jpg")}
    assert (target_dir / "cover-2.jpg").is_file()
    assert not (target_dir / "cover-0.jpg").exists()


async def test_generate_covers_fallback_staggers_seek_per_dish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unknown duration: seek 3s + 2s * dish_index so siblings still differ
    (a too-long seek just fails that frame — None, acceptable)."""
    calls: list[list[str]] = []
    monkeypatch.setattr(covers.subprocess, "run", _run_recorder(calls, probe_stdout=None))
    video = tmp_path / "video.mp4"
    video.write_bytes(b"tiny fake file")

    result = await covers.generate_covers(
        video, tmp_path / "archive", [(0, 1 / 3), (2, 0.75)]
    )

    assert result == {
        0: str(tmp_path / "archive" / "cover-0.jpg"),
        2: str(tmp_path / "archive" / "cover-2.jpg"),
    }
    ffmpeg_calls = [call for call in calls if call[0] == "ffmpeg"]
    seeks = [call[call.index("-ss") + 1] for call in ffmpeg_calls]
    assert seeks == ["3.000", "7.000"]  # 3.0 + 2.0 * dish_index


async def test_generate_covers_ffmpeg_failure_yields_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        covers.subprocess, "run", _run_recorder(calls, probe_stdout=b"60.0\n", ffmpeg_ok=False)
    )
    result = await covers.generate_covers(tmp_path / "video.mp4", tmp_path / "a", [(0, 0.5)])
    assert result == {0: None}


async def test_generate_covers_missing_binary_yields_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def no_binary(args, capture_output, timeout):
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(covers.subprocess, "run", no_binary)
    result = await covers.generate_covers(
        tmp_path / "video.mp4", tmp_path / "a", [(0, 1 / 3), (1, 2 / 3)]
    )
    assert result == {0: None, 1: None}


async def test_generate_covers_never_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def exploding(video_path, target_dir, frames):
        raise RuntimeError("boom")

    monkeypatch.setattr(covers, "_generate_covers_sync", exploding)
    result = await covers.generate_covers(tmp_path / "video.mp4", tmp_path / "a", [(0, 0.5)])
    assert result == {0: None}


# ─── archived_video_path (backfill input discovery) ──────────────────────────


def test_archived_video_path_picks_largest_video(tmp_path: Path) -> None:
    (tmp_path / "cover-0.jpg").write_bytes(b"jpeg" * 100)  # never a candidate
    (tmp_path / "clip.mp4").write_bytes(b"v" * 10)
    (tmp_path / "main.webm").write_bytes(b"v" * 1000)
    (tmp_path / "notes.txt").write_bytes(b"t" * 5000)  # wrong suffix
    assert covers.archived_video_path(tmp_path) == tmp_path / "main.webm"


def test_archived_video_path_none_when_missing_or_empty(tmp_path: Path) -> None:
    assert covers.archived_video_path(tmp_path / "nope") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert covers.archived_video_path(empty) is None
