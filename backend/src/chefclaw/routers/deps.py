"""Shared router dependencies + the ChefclawError → HTTP mapping."""

from typing import Annotated

from fastapi import Depends
from fastapi.responses import JSONResponse

from chefclaw import db
from chefclaw.config import Settings, get_settings
from chefclaw.errors import ChefclawError
from chefclaw.schemas import ErrorBody
from chefclaw.services.jobs import default_source_adapters
from chefclaw.services.repo import JobStore, PostgresJobStore, PostgresSpendReader, SpendReader
from chefclaw.sources import SourceAdapter

__all__ = [
    "error_response",
    "get_job_store",
    "get_source_adapters",
    "get_spend_reader",
    "http_status_for",
]

# Typed taxonomy → HTTP status for errors surfaced at request time (the
# worker path stores them on the job instead). ConfigError is a 503: the
# operator must fix the environment; nothing about the request is wrong.
_STATUS_BY_ERROR_TYPE = {
    "unsupported_url": 400,
    "config_error": 503,
    "download_failed": 502,
    "rate_limited": 503,
    "cookies_expired": 503,
    "upload_too_large": 413,
}


def http_status_for(err: ChefclawError) -> int:
    return _STATUS_BY_ERROR_TYPE.get(err.error_type, 500)


def error_response(status_code: int, error_type: str, detail: str) -> JSONResponse:
    """The typed error body: {error_type, detail} at top level."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorBody(error_type=error_type, detail=detail).model_dump(),
    )


def get_job_store(settings: Annotated[Settings, Depends(get_settings)]) -> JobStore:
    """The real store; tests override this dependency with a fake."""
    return PostgresJobStore(db.get_sessionmaker(), settings)


def get_source_adapters(
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[SourceAdapter]:
    return default_source_adapters(settings)


def get_spend_reader(settings: Annotated[Settings, Depends(get_settings)]) -> SpendReader:
    """The real ledger reader; tests override this dependency with a fake."""
    return PostgresSpendReader(db.get_sessionmaker(), settings)
