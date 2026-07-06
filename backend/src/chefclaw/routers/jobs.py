"""GET /api/jobs/{id} — the polling endpoint the UI watches."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from chefclaw.auth import require_owner
from chefclaw.routers.deps import error_response, get_job_store
from chefclaw.schemas import ErrorBody, JobOut
from chefclaw.services.repo import JobStore

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    response_model=JobOut,
    responses={404: {"model": ErrorBody}},
)
async def get_job(
    job_id: uuid.UUID,
    owner_id: Annotated[uuid.UUID, Depends(require_owner)],
    store: Annotated[JobStore, Depends(get_job_store)],
) -> JobOut | JSONResponse:
    job = await store.get_job(job_id, owner_id)
    if job is None:
        return error_response(404, "not_found", f"no job {job_id}")
    return JobOut.model_validate(job)
