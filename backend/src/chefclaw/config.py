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

    # Deliberately raw strings: parsed fail-closed at point of use (unset or
    # unparseable => NO paid calls, surfaced as a typed ConfigError — §16.8).
    monthly_llm_budget_usd: str = ""
    max_extraction_attempts_per_day: str = ""
    media_retention: str = "keep"  # keep | discard — the retained low-res archive

    # ── Extraction (Phase 2) ────────────────────────────────────────────────
    # Extractor selection: "fake" is the SAFE default (tests, golden suite, no
    # accidental spend); compose sets "gemini" for the real stack.
    chefclaw_extractor: str = "fake"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"  # model id is config, never hardcoded
    gemini_media_resolution: str = "low"  # escalate only if overlay text is missed

    # ── Sources (Phase 2) ───────────────────────────────────────────────────
    # Source-adapter selection (plan §16.9 golden-suite split): "real" registers
    # the platform adapters; "fake" swaps in the canned FakeSource so the golden
    # stack never touches a platform. Unknown values fail closed (ConfigError).
    chefclaw_sources: str = "real"
    # Rednote access is TIERED (plan §16.10): guest (no cookie) is the default;
    # a hard-isolated throwaway cookie is tier 1; the main account NEVER.
    xhs_sidecar_url: str = ""  # in compose: http://xhs:<port>; empty = source disabled
    xhs_cookie: str = ""
    xhs_user_agent: str = ""
    xhs_cookie_set_date: str = ""  # human-written at every refresh; health warns off it
    bilibili_cookie: str = ""  # optional — anonymous is the default tier

    # ── Media dirs (Phase 2) ────────────────────────────────────────────────
    media_dir: str = "/data/media"  # retained archive — named volume, irreplaceable
    scratch_dir: str = ""  # empty = system temp; ephemeral by design

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
