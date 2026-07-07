"""FakeImageGenerator — the config-selectable safe default (V2-E).

Zero network, zero spend, deterministic. The worker tests and golden suite
drive the illustration stage through this adapter: it returns a tiny valid
image header (tests only check that a file lands, not that it decodes), records
its calls, and can inject a failure to exercise the best-effort miss path.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from chefclaw.images import ImageResult

FAKE_IMAGE_MODEL_ID = "fake-image"

# A real, decodable 48×30 solid dark-slate baseline JPEG (ffmpeg-encoded). The
# fake is the DEFAULT generator, so the dev/golden card must render a clean
# placeholder tile — not a broken-image glyph from undecodable bytes. Real
# illustrations replace it in production; the flat tile just proves the pipeline.
_PLACEHOLDER_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010200000100010000fffe00104c61766336312e31392e3130"
    "3100ffdb0043000804040404040505050505050606060606060606060606060607070708"
    "080807070706060707080808080909090808080809090a0a0a0c0c0b0b0e0e0e111114ff"
    "c4004c000101000000000000000000000000000000070101010000000000000000000000"
    "000000000210010000000000000000000000000000000011010000000000000000000000"
    "0000000000ffc0001108001e003003012200021100031100ffda000c0301000211031100"
    "3f008a00b0000000000000001fffd9"
)


@dataclass
class FakeImageCall:
    """One recorded generate() invocation — worker tests assert against these."""

    prompt: str


class FakeImageGenerator:
    """ImageGeneratorAdapter double with injection ergonomics.

    - ``failure`` — raised as-is on every generate() call (pass any taxonomy
      error to drive the best-effort miss path).
    - ``image_bytes`` — the returned placeholder (default: a tiny valid JPEG).
    - ``cost_usd`` — the flat per-image cost the ledger records (default 0 —
      the fake is genuinely free).
    - ``calls`` — every invocation recorded for assertion.
    """

    def __init__(
        self,
        failure: Exception | None = None,
        image_bytes: bytes | None = None,
        cost_usd: Decimal = Decimal("0"),
    ) -> None:
        self._failure = failure
        self._image_bytes = image_bytes if image_bytes is not None else _PLACEHOLDER_JPEG
        self._cost_usd = cost_usd
        self.calls: list[FakeImageCall] = []

    async def generate(self, prompt: str) -> ImageResult:
        self.calls.append(FakeImageCall(prompt))
        if self._failure is not None:
            raise self._failure
        return ImageResult(
            image_bytes=self._image_bytes,
            model_id=FAKE_IMAGE_MODEL_ID,
            cost_usd=self._cost_usd,
        )
