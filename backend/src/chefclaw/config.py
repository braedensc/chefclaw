"""Application settings, read from environment variables.

Secrets never appear in this file — only names and local-dev placeholders.
The database URL is always assembled from parts; a full URL-with-password
literal must never exist anywhere in the codebase.
"""

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration.

    Field names map to env vars case-insensitively (e.g. ``chefclaw_api_token``
    <- ``CHEFCLAW_API_TOKEN``).
    """

    model_config = SettingsConfigDict(extra="ignore")

    # DEAD post-M2 (kept only so old .env.local files don't error on the unknown
    # key). The bearer branch was removed at the M2 cutover — auth is cookie
    # sessions now (auth.require_owner), and HTTPBearer is gone from the OpenAPI
    # security scheme. This grants NO access; drop it from .env.local at the next
    # deploy (docs/SECURITY.md — the token→session cutover). Still on the Sentry
    # scrub denylist as belt-and-braces.
    chefclaw_api_token: str = ""

    # ── M2 auth (ADR 2026-07-07-m2-accounts-and-invites) ────────────────────
    # Auth-provider selection, mirroring CHEFCLAW_EXTRACTOR. "fake" is the SAFE
    # default: the unit tier short-circuits require_owner to chefclaw_fake_owner_id
    # (no cookie/session read), and the golden tier drives the REAL callback
    # through a FakeOAuthProvider (the invite gate + session insert run for real).
    # "google" constructs the real provider, fail-closed on empty creds. Unknown
    # ⇒ ConfigError at startup (auth.assert_prod_auth_safe).
    chefclaw_auth_provider: str = "fake"
    # Google OAuth client (Cloud Console — a DEPLOY human precondition). The
    # SECRET is a SERVER secret: it must NEVER be a VITE_* var (Hard Rule 4).
    # Empty creds while chefclaw_auth_provider="google" ⇒ ConfigError.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_url: str = ""
    # The owner id the FAKE auth provider resolves to (== tests' OWNER_ID). Only
    # consulted when chefclaw_auth_provider="fake".
    chefclaw_fake_owner_id: str = "01890000-0000-7000-8000-000000000001"
    # Absolute session lifetime for the opaque server-side sessions (720h = 30d).
    session_ttl_hours: int = 720
    # Idle-timeout (V2-D): a session unused for longer than this stops resolving
    # BEFORE its absolute expires_at (last_seen_at is recorded on each resolve —
    # this makes it load-bearing). Comfortably above the 5-min last_seen_at write
    # throttle so a live session is never falsely expired. 0 DISABLES the idle
    # check (absolute TTL still applies). Default 14 days.
    session_idle_timeout_hours: int = 336

    # ── Rate limiting (V2-D security audit) ─────────────────────────────────
    # Trailing-window request throttle (append-only event rows — no mutable
    # counter to race). Two buckets, 60-second window, per-minute caps:
    #  - authenticated: keyed per SESSION — a generous backstop against a
    #    runaway/compromised session (real browsing bursts image loads, so this
    #    is well above human use; it stops abuse, not normal use).
    #  - public: keyed per client IP — covers the pre-auth endpoints
    #    (/api/auth/google/callback, /api/invites/{token}); strict enough that
    #    neither can be hammered.
    # 0 DISABLES that bucket (fail-open). See chefclaw.ratelimit.
    rate_limit_authenticated_per_minute: int = 300
    rate_limit_public_per_minute: int = 30

    # ── M2 invites + transactional email (PR 3) ─────────────────────────────
    # Email-provider selection, mirroring the auth/extractor seams. "fake"
    # (default) is ConsoleEmailAdapter (logs the activation link, zero network);
    # "ses" is AWS SES (empty email_from/ses_region ⇒ ConfigError). Unknown ⇒
    # ConfigError. A 'vps' env with the fake email provider fails the boot
    # (assert_prod_auth_safe, critique M7 — same footgun as fake auth).
    chefclaw_email: str = "fake"
    email_from: str = ""  # the verified SES sender ("chefclaw <no-reply@…>")
    ses_region: str = ""  # AWS region for SES; boto3 creds via the IAM-role chain
    # Public base URL for building the invite activation link
    # ({public_base_url}/invite/{token}). Empty ⇒ ConfigError at create-invite
    # (an invite email with a localhost link is useless).
    public_base_url: str = ""
    invite_ttl_hours: int = 168  # 7 days
    # The seed-admin bootstrap email (critique M6b): the first-owner
    # bootstrap-claim adopts the migration-seeded admin row ONLY if the verified
    # OAuth email equals this. EMPTY ⇒ bootstrap-claim is disabled entirely (no
    # "first stranger to sign in becomes admin" race). Normalized lower/trim.
    bootstrap_admin_email: str = ""

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
    # keep | discard — the retained source-video archive. Default DISCARD
    # (Braeden's 2026-07-06 V2-E decision): card covers are now generated
    # cartoon illustrations built from TEXT fields, not real video frames, so
    # the source video no longer needs retaining (it's also the legally
    # riskiest artifact — a literal reproduction). Overridable to "keep" for
    # re-extraction insurance or the optional provenance thumbnail.
    media_retention: str = "discard"
    # Upload size cap (tier-2 file upload). Enforced pre-parse in middleware so
    # an oversized upload is rejected 413 BEFORE Starlette spools it to disk —
    # an unbounded upload endpoint lets an authed client fill the box's disk.
    # A few-minute cooking video is tens of MB; 500 leaves generous headroom.
    max_upload_mb: int = 500

    # ── Extraction (Phase 2) ────────────────────────────────────────────────
    # Extractor selection: "fake" is the SAFE default (tests, golden suite, no
    # accidental spend); compose sets "gemini" for the real stack.
    chefclaw_extractor: str = "fake"
    gemini_api_key: str = ""
    # Model id is config, never hardcoded. TIER FLIP (M3): "gemini-2.5-flash" is
    # the free/cheap default; "gemini-2.5-pro" is the PAID tier — higher quality
    # at ~4x in / ~3x out token cost (both priced, padded, in
    # spend.GEMINI_PRICING, so the fail-closed budget gate bounds pro spend
    # unchanged). GEMINI_MODEL is the GLOBAL default everyone gets; a per-user
    # paid_tier flag (users.paid_tier, set by the admin budget endpoint) bumps
    # THAT account to GEMINI_PAID_MODEL instead — see
    # extractors.extractor_settings_for_tier and
    # docs/adr/2026-07-07-per-user-budget-caps.md.
    gemini_model: str = "gemini-2.5-flash"
    gemini_paid_model: str = "gemini-2.5-pro"  # the per-user paid_tier model
    gemini_media_resolution: str = "low"  # base resolution; escalate only if overlay text is missed
    # One-shot media-resolution escalation (V2-C, ADR 2026-07-07-extractor-
    # robustness-qa). EMPTY (default) = escalation OFF: extraction uses the
    # base resolution and the unchanged v4 prompt — the safe, no-extra-spend
    # default. Set to a resolution ABOVE the base (e.g. "high" when base is
    # "low") to enable it: the Gemini adapter then uses the v5 prompt, and when
    # the model reports on-screen text it could not read at the base resolution,
    # it retries the SAME uploaded video ONCE at this ceiling (one extra paid
    # call, bounded, summed into the attempt's ledger row). Unknown value, or a
    # value not strictly above the base, ⇒ ConfigError (fail-closed).
    gemini_media_resolution_max: str = ""
    # Qwen fallback via DashScope OpenAI-compatible mode (CHEFCLAW_EXTRACTOR=qwen;
    # fail-closed when keyless). Region/data-governance review is a HUMAN
    # precondition before first real use — docs/SERVICES.md §3. The base URL is
    # config so that review can pick the region deliberately.
    dashscope_api_key: str = ""
    dashscope_model: str = "qwen3-vl-plus"  # config, never trusted as current
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    # ── Card covers (V2-F, 2026-07-07) ──────────────────────────────────────
    # The cover-generation mode. "sprite" (the DEFAULT) assigns a curated
    # original dish-sprite id during extraction and renders it INLINE from the
    # bundled catalog — zero spend, no illustration job, shippable-safe. "fake"
    # is the canned-blob path (golden/tests exercise the /image route); "gemini"
    # is the legacy paid text-only illustration (demoted from default, V2-E).
    # A real private video-frame cover is a SEPARATE layer over sprite mode,
    # gated by chefclaw_real_covers below (never a value of this knob).
    chefclaw_image_generator: str = "sprite"
    # V2-F private real-frame layer, the GLOBAL half of a two-gate grant (the
    # per-user users.real_covers_enabled is the other). Default FALSE ⇒ pure
    # sprites: no beauty-shot frame is ever captured OR served. Meaningful only
    # in sprite mode. A frame reaches a viewer ONLY when this is true AND the
    # requesting owner is granted — so multi-user/public stays sprite-only and a
    # creator frame never crosses to an ungranted viewer.
    chefclaw_real_covers: bool = False
    # !!! CONFIRM this model id at deploy — image models sunset FAST and this
    # cannot be verified from here (Gemini 2.5 Flash Image / Imagen 4 both
    # retire Aug–Oct 2026). "Nano Banana 2". !!!
    gemini_image_model: str = "gemini-3.1-flash-image"
    # Flat per-image cost written to the spend ledger (image models bill per
    # image, not per token). Tune to the model's real published price at deploy
    # (~$0.067/image single, ~$0.034 batch as of 2026-07).
    gemini_image_cost_usd: Decimal = Decimal("0.067")

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
    # Fetch proxy (M-Deploy Rednote escalation ladder — 2026-07-06 ADR): routes
    # ONLY platform-fetch traffic through a proxy — the sidecar detail call's
    # `proxy` param (the sidecar's own platform call), the api's media
    # downloads and short-link resolution, and yt-dlp. Ladder rungs b (home
    # exit node via Tailscale SOCKS5), c (commercial residential proxy), and
    # d (home relay) are all this ONE knob. Empty = direct (the default).
    # The api→sidecar hop is compose-internal and is NEVER proxied.
    chefclaw_fetch_proxy: str = ""

    # ── Media dirs (Phase 2) ────────────────────────────────────────────────
    media_dir: str = "/data/media"  # retained archive — named volume, irreplaceable
    scratch_dir: str = ""  # empty = system temp; ephemeral by design

    # Directory of the built SPA to serve at "/" (prod mode). Unset => skip.
    # In compose this points at the built frontend, e.g. ../frontend/dist.
    chefclaw_static_dir: str = ""

    # ── Observability (V2-A ADR) ────────────────────────────────────────────
    # Sentry is opt-in by presence: empty DSN ⇒ the SDK is never initialised
    # (dev/CI/tests send zero events). The DSN is an ingest address, not a
    # credential — it still lives in .env.local per the three-stores model.
    sentry_dsn: str = ""
    sentry_environment: str = "local"  # local | vps — tags every event
    sentry_release: str = ""  # git SHA, baked at image build (GIT_SHA build arg)
    chefclaw_log_format: str = "json"  # json | text (anything else ⇒ json)
    chefclaw_log_level: str = "INFO"

    # ── Backups (Phase 4) ───────────────────────────────────────────────────
    # scripts/backup.sh (host-side, launchd-scheduled) writes ops/last-backup.json;
    # compose bind-mounts ./ops read-only at /data/ops so /api/health can report
    # backup staleness. Missing file = 'not_configured', never an error.
    backup_state_file: str = "/data/ops/last-backup.json"

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL assembled from parts."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def session_cookie_secure(self) -> bool:
        """The ``Secure`` flag for the session + oauth_tx cookies — DERIVED from
        the deploy env, NEVER a standalone human toggle (critique M8): prod
        (``sentry_environment == 'vps'``) ⇒ always Secure; local/dev ⇒ not
        Secure so http://localhost works. Same 'vps' signal the prod auth guard
        (auth.assert_prod_auth_safe) uses."""
        return self.sentry_environment == "vps"


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached Settings; also a FastAPI dependency (overridable in tests)."""
    return Settings()
