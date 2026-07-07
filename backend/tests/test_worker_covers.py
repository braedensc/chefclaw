"""V2-F cover-system worker tests — CI tier: no network, no database, no ffmpeg.

Sprite mode (the app default) assigns a cover_sprite_id during extraction and
enqueues NO illustration job; a low-confidence assignment falls back to
``unknown-dish`` and logs a ``cover_misses`` row. The private real-frame layer
(sprite mode + CHEFCLAW_REAL_COVERS) grabs one frame via an INJECTED fake
grabber — real ffmpeg is never shelled out here.
"""

from __future__ import annotations

from pathlib import Path

from chefclaw.extractors.fake import FakeExtractor, default_dish
from chefclaw.services.jobs import enqueue_extract
from tests.fakes import FakeJobStore
from tests.test_worker import (
    FAKE_URL,
    OWNER_ID,
    claim_and_process,
    illustration_jobs,
    image_spend_rows,
    make_settings,
    make_source,
    make_worker,
)


def _dish_with(**overrides) -> dict:
    dish = default_dish()
    dish.update(overrides)
    return dish


async def test_runtime_override_flips_cover_mode_without_restart(tmp_path: Path) -> None:
    """ADR admin-config-panel: the worker resolves effective settings PER JOB via
    store.effective_settings, so an app_config override wins over the boot base
    with no restart. Base settings say 'sprite' (enqueues no illustration); an
    override to 'fake' makes the very next job enqueue an illustration job."""
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path, chefclaw_image_generator="sprite")
    # The runtime override an admin would have set via PATCH /api/admin/config.
    store.config_overrides = {"chefclaw_image_generator": "fake"}
    worker, _ = make_worker(store, source, settings, FakeExtractor())

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    # Effective mode 'fake' (override) beat base 'sprite': an illustration job
    # was enqueued for the stored recipe.
    assert len(illustration_jobs(store)) == 1


async def test_sprite_mode_assigns_cover_and_enqueues_no_illustration(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path, chefclaw_image_generator="sprite")
    worker, _ = make_worker(store, source, settings, FakeExtractor())

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    # The fake dish carries a valid model pick — trusted as-is, no fallback.
    assert store.recipes[0].cover_sprite_id == "red-braised-pork"
    # Sprite mode: covers are inline sprites — no illustration job, zero spend.
    assert illustration_jobs(store) == []
    assert image_spend_rows(store) == []
    assert store.cover_misses == []


async def test_sprite_mode_unknown_dish_falls_back_and_logs_a_miss(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(tmp_path, chefclaw_image_generator="sprite")
    dish = _dish_with(
        dish_name={"en": "Zqxrb Flooble", "original": None},
        cuisine_type=None,
        tags=[],
        cover_sprite_id=None,  # model omitted → deterministic matcher runs
    )
    worker, _ = make_worker(store, source, settings, FakeExtractor(dishes=[dish]))

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    await claim_and_process(worker, store)

    recipe = store.recipes[0]
    assert recipe.cover_sprite_id == "unknown-dish"
    assert len(store.cover_misses) == 1
    miss = store.cover_misses[0]
    assert miss.reason == "no_match"
    assert miss.recipe_id == recipe.id
    assert miss.owner_id == OWNER_ID
    assert miss.resolved_sprite_id == "unknown-dish"


async def test_real_frame_captured_when_globally_enabled(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    settings = make_settings(
        tmp_path, chefclaw_image_generator="sprite", chefclaw_real_covers=True
    )
    dish = _dish_with(beauty_shot_timestamp_seconds=42)
    grabbed: list[tuple[Path, float, Path]] = []

    async def fake_grabber(video_path: Path, timestamp: float, out_path: Path) -> str | None:
        grabbed.append((video_path, timestamp, out_path))
        return str(out_path)  # pretend ffmpeg wrote the frame

    worker, _ = make_worker(
        store, source, settings, FakeExtractor(dishes=[dish]), frame_grabber=fake_grabber
    )

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    job = await claim_and_process(worker, store)

    assert job.status == "stored"
    recipe = store.recipes[0]
    assert recipe.image_url is not None
    assert recipe.image_style_version == "video-frame-v1"
    assert recipe.cover_sprite_id == "red-braised-pork"  # sprite still assigned underneath
    # The model's timestamp (42s, within the 300s fake duration) was used.
    assert len(grabbed) == 1
    assert grabbed[0][1] == 42.0
    assert grabbed[0][2].name == "frame-0.jpg"
    # Real frames never go through the paid image ledger.
    assert image_spend_rows(store) == []
    assert illustration_jobs(store) == []


async def test_real_frames_off_by_default_no_capture(tmp_path: Path) -> None:
    store, source = FakeJobStore(), make_source()
    # sprite mode but CHEFCLAW_REAL_COVERS defaults OFF — no capture at all.
    settings = make_settings(tmp_path, chefclaw_image_generator="sprite")
    dish = _dish_with(beauty_shot_timestamp_seconds=42)
    grabbed: list = []

    async def fake_grabber(video_path, timestamp, out_path):
        grabbed.append(out_path)
        return str(out_path)

    worker, _ = make_worker(
        store, source, settings, FakeExtractor(dishes=[dish]), frame_grabber=fake_grabber
    )

    await enqueue_extract(store, OWNER_ID, FAKE_URL, [source], settings)
    await claim_and_process(worker, store)

    assert store.recipes[0].image_url is None  # sprite-only
    assert grabbed == []  # the grabber was never called


async def test_backfill_assigns_sprites_and_skips_illustrations_in_sprite_mode(
    tmp_path: Path,
) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path, chefclaw_image_generator="sprite")
    # A pre-V2-F recipe with no sprite yet.
    recipe = store.seed_recipe(
        owner_id=OWNER_ID,
        cover_sprite_id=None,
        document={"dish_name": {"en": "Margherita Pizza"}, "cuisine_type": "Italian"},
        tags=["pizza"],
    )
    worker, _ = make_worker(store, make_source(), settings, FakeExtractor())

    await worker.backfill_covers()

    assert recipe.cover_sprite_id == "margherita-pizza"
    assert illustration_jobs(store) == []  # sprite mode: never enqueues one


async def test_backfill_logs_a_miss_for_an_unmatchable_recipe(tmp_path: Path) -> None:
    store = FakeJobStore()
    settings = make_settings(tmp_path, chefclaw_image_generator="sprite")
    recipe = store.seed_recipe(
        owner_id=OWNER_ID,
        cover_sprite_id=None,
        document={"dish_name": {"en": "Zqxrb Flooble"}, "cuisine_type": None},
        tags=[],
    )
    worker, _ = make_worker(store, make_source(), settings, FakeExtractor())

    await worker.backfill_sprites()

    assert recipe.cover_sprite_id == "unknown-dish"
    assert len(store.cover_misses) == 1
    assert store.cover_misses[0].reason == "no_match"
