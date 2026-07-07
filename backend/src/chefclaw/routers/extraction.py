"""POST /api/recipes/extract + /upload — the two job-producing endpoints.

Both ALWAYS return the job resource (plan §16.2): 202 when a new job was
enqueued, 200 when canonical dedupe matched an existing active/completed job.
Never a recipe body.
"""

import tempfile
import uuid
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from chefclaw import errors
from chefclaw.auth import require_owner
from chefclaw.config import Settings, get_settings
from chefclaw.routers.deps import (
    error_response,
    get_job_store,
    get_source_adapters,
    http_status_for,
)
from chefclaw.schemas import ErrorBody, ExtractRequest, JobOut
from chefclaw.services import jobs as jobs_service
from chefclaw.services.repo import JobStore
from chefclaw.sources import SourceAdapter

router = APIRouter(prefix="/api/recipes", tags=["extraction"])

_UPLOAD_CHUNK_BYTES = 1024 * 1024

_EXTRACT_RESPONSES = {
    200: {"model": JobOut, "description": "Existing job (canonical dedupe hit)"},
    400: {"model": ErrorBody},
    502: {"model": ErrorBody},
    503: {"model": ErrorBody},
}
# /upload can additionally 413 (over MAX_UPLOAD_MB) — the size cap.
_UPLOAD_RESPONSES = {**_EXTRACT_RESPONSES, 413: {"model": ErrorBody}}


@router.post(
    "/extract",
    status_code=202,
    response_model=JobOut,
    responses=_EXTRACT_RESPONSES,
)
async def extract_recipe(
    body: ExtractRequest,
    response: Response,
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    store: Annotated[JobStore, Depends(get_job_store)],
    adapters: Annotated[list[SourceAdapter], Depends(get_source_adapters)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    try:
        job, existing = await jobs_service.enqueue_extract(
            store, owner_id, body.url, adapters, settings
        )
    except errors.ChefclawError as err:
        return error_response(http_status_for(err), err.error_type, str(err))
    response.status_code = 200 if existing else 202
    return JobOut.model_validate(job)


@router.post(
    "/upload",
    status_code=202,
    response_model=JobOut,
    responses=_UPLOAD_RESPONSES,
)
async def upload_recipe_video(
    response: Response,
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    store: Annotated[JobStore, Depends(get_job_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
    provenance_url: Annotated[str | None, Form()] = None,
    platform_hint: Annotated[str | None, Form()] = None,
):
    """The §16.10 tier-2 floor: manual save + upload. Same job contract; the
    content-addressed canonical id means re-uploading the same bytes dedupes
    exactly like a re-pasted URL."""
    # provenance_url is free-form here (the paste path is host-allowlisted; this
    # isn't). It becomes the recipe's source_url, which the SPA renders as a
    # "View original" href — so refuse anything but http(s) at the boundary, or a
    # javascript:/data: URL would be a stored XSS link (V2-D audit finding).
    if provenance_url and provenance_url.strip():
        scheme = urlparse(provenance_url).scheme.lower()
        if scheme not in ("http", "https"):
            return error_response(
                400,
                "unsupported_url",
                "provenance_url must be an http(s) link (or omitted).",
            )
    incoming_dir = (
        Path(settings.scratch_dir or tempfile.gettempdir()) / "chefclaw-uploads" / "incoming"
    )
    incoming_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "upload.bin").suffix
    tmp_path = incoming_dir / f"{uuid.uuid4().hex}{suffix}"
    # Backstop to the pre-parse middleware cap: a client that omitted
    # Content-Length (chunked) slips past the middleware, so bound the bytes we
    # actually write here — the pipeline must never receive an over-cap file.
    max_upload_bytes = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with tmp_path.open("wb") as out:
            while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > max_upload_bytes:
                    raise errors.UploadTooLargeError(
                        f"upload exceeds the {settings.max_upload_mb} MB limit "
                        "(MAX_UPLOAD_MB) — save a shorter or lower-resolution clip"
                    )
                out.write(chunk)
        job, existing = await jobs_service.enqueue_upload(
            store,
            owner_id,
            tmp_path,
            provenance_url,
            platform_hint,
            settings,
            original_filename=file.filename,
        )
    except errors.ChefclawError as err:
        return error_response(http_status_for(err), err.error_type, str(err))
    finally:
        tmp_path.unlink(missing_ok=True)  # ingest copied it content-addressed
    response.status_code = 200 if existing else 202
    return JobOut.model_validate(job)
