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


# ─── fraction math ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("dish_count", "expected"),
    [(1, [0.5]), (2, [1 / 3, 2 / 3]), (3, [0.25, 0.5, 0.75])],
)
def test_cover_fractions_spread_across_the_video(dish_count: int, expected: list[float]) -> None:
    assert covers.cover_fractions(dish_count) == pytest.approx(expected)


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

    result = await covers.generate_covers(video, target_dir, [1 / 3, 2 / 3])

    assert result == [str(target_dir / "cover-0.jpg"), str(target_dir / "cover-1.jpg")]
    assert (target_dir / "cover-0.jpg").is_file()
    ffmpeg_calls = [call for call in calls if call[0] == "ffmpeg"]
    seeks = [call[call.index("-ss") + 1] for call in ffmpeg_calls]
    assert seeks == ["40.000", "80.000"]  # 120s * 1/3, 120s * 2/3


async def test_generate_covers_falls_back_to_3s_without_duration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(covers.subprocess, "run", _run_recorder(calls, probe_stdout=None))
    video = tmp_path / "video.mp4"
    video.write_bytes(b"tiny fake file")

    result = await covers.generate_covers(video, tmp_path / "archive", [0.5])

    assert result == [str(tmp_path / "archive" / "cover-0.jpg")]
    ffmpeg_call = next(call for call in calls if call[0] == "ffmpeg")
    assert ffmpeg_call[ffmpeg_call.index("-ss") + 1] == "3.000"


async def test_generate_covers_ffmpeg_failure_yields_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        covers.subprocess, "run", _run_recorder(calls, probe_stdout=b"60.0\n", ffmpeg_ok=False)
    )
    result = await covers.generate_covers(tmp_path / "video.mp4", tmp_path / "a", [0.5])
    assert result == [None]


async def test_generate_covers_missing_binary_yields_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def no_binary(args, capture_output, timeout):
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(covers.subprocess, "run", no_binary)
    result = await covers.generate_covers(tmp_path / "video.mp4", tmp_path / "a", [1 / 3, 2 / 3])
    assert result == [None, None]


async def test_generate_covers_never_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def exploding(video_path, target_dir, fractions):
        raise RuntimeError("boom")

    monkeypatch.setattr(covers, "_generate_covers_sync", exploding)
    result = await covers.generate_covers(tmp_path / "video.mp4", tmp_path / "a", [0.5])
    assert result == [None]


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
