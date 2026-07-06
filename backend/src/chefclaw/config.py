"""Application settings, read from environment variables.

Secrets never appear in this file — only names and local-dev placeholders.
The database URL is always assembled from parts; a full URL-with-password
literal must never exist anywhere in the codebase.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration.

    Field names map to env vars case-insensitively (e.g. ``chefclaw_api_token``
    <- ``CHEFCLAW_API_TOKEN``).
    """

    model_config = SettingsConfigDict(extra="ignore")

    # Auth is disabled-closed: an empty token means every request gets a 401
    # telling the operator to set CHEFCLAW_API_TOKEN (see auth.require_owner).
    chefclaw_api_token: str = ""

    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_user: str = "chefclaw"
    # Local-dev placeholder only — overridden via env for any real deployment.
    db_password: str = "chefclaw-local-dev"
    db_name: str = "chefclaw"

    # Deliberately a raw string: Phase 2 parses it fail-closed (unset or
    # unparseable => NO paid calls, surfaced as a typed config error).
    monthly_llm_budget_usd: str = ""
    media_retention: str = "keep"

    # Directory of the built SPA to serve at "/" (prod mode). Unset => skip.
    # In compose this points at the built frontend, e.g. ../frontend/dist.
    chefclaw_static_dir: str = ""

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL assembled from parts."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached Settings; also a FastAPI dependency (overridable in tests)."""
    return Settings()
