"""Local-file source — the zero-platform-risk escape hatch (plan §16.10 tier 2).

Manual save + file upload: extraction must never *require* platform access.
The canonical id is CONTENT-ADDRESSED (``file-<sha256[:16]>``), so re-uploading
the same video dedupes exactly like a re-pasted URL would (§16.1).

``LocalFileSource`` is invoked explicitly by the upload path via ``ingest()``
— it is never URL-matched and is not registered with ``resolve_source``.
``matches()``/``resolve()`` exist only so a defensively-registered instance
degrades safely.
"""

import asyncio
import hashlib
import shutil
from pathlib import Path

from chefclaw import errors
from chefclaw.sources import CanonicalRef, FetchedMedia

_HASH_CHUNK = 1024 * 1024


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class LocalFileSource:
    """Ingest an uploaded video file with optional provenance.

    ``dest_dir`` is fixed at construction (the upload path knows its media
    directory up front); ``ingest()`` is the fetch-equivalent: it hashes the
    content, copies the file into ``dest_dir`` under its content-addressed
    name, and returns the same ``(CanonicalRef, FetchedMedia)`` pair the
    URL adapters produce via resolve()+fetch().
    """

    platform = "local"

    def __init__(self, dest_dir: Path) -> None:
        self._dest_dir = dest_dir

    def matches(self, url: str) -> bool:
        return False  # never URL-matched — the upload path invokes ingest()

    async def resolve(self, url: str) -> CanonicalRef:
        raise errors.UnsupportedUrlError(
            "LocalFileSource has no URL form — use ingest(file_path, ...)"
        )

    async def ingest(
        self,
        file_path: Path,
        provenance_url: str | None,
        platform_hint: str | None,
    ) -> tuple[CanonicalRef, FetchedMedia]:
        """Hash + copy the uploaded file; returns the canonical ref and media.

        Metadata is deliberately bare: a filename is not a title and the
        adapter never guesses (Hard Rule 7) — provenance/hints ride in
        ``extra`` for the extractor and UI to use as context, not as data.
        """
        if not file_path.is_file():
            raise errors.DownloadFailedError(f"uploaded file not found: {file_path}")

        # Hashing and copying are blocking I/O — keep them off the event loop.
        sha256 = await asyncio.to_thread(_sha256_of, file_path)
        canonical_id = f"file-{sha256[:16]}"

        suffix = file_path.suffix.lower()
        target = self._dest_dir / f"{canonical_id}{suffix}"
        self._dest_dir.mkdir(parents=True, exist_ok=True)
        if not target.exists():  # content-addressed: same bytes, same file
            await asyncio.to_thread(shutil.copy2, file_path, target)

        ref = CanonicalRef(
            platform=self.platform,
            canonical_id=canonical_id,
            fetch_url=provenance_url or f"local://{canonical_id}",
        )
        media = FetchedMedia(
            video_path=target,
            title=None,
            creator=None,
            duration_seconds=None,
            extra={
                "sha256": sha256,
                "original_filename": file_path.name,
                "provenance_url": provenance_url,
                "platform_hint": platform_hint,
            },
        )
        return ref, media
