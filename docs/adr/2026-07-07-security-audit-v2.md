# V2-D: Security audit + public-exposure readiness

**Date:** 2026-07-07 · **Context:** milestone V2-D, branch `feat/security-audit-v2` · follows the M2 accounts/invites ADR (`2026-07-07-m2-accounts-and-invites.md`).

## Decision

The formal security pass before (optionally) going beyond Tailscale. A multi-agent `/security-review` swept every surface (auth/OAuth/session/invite, platform sources/worker, repo SQL, frontend, infra); findings were triaged, the real ones fixed, the rest recorded as residuals. Shipped controls:

- **API rate limiting** — a new `request_events` append-only table + `chefclaw.ratelimit` middleware. Trailing-60s-window count per key, two buckets: **authenticated** (per session, `RATE_LIMIT_AUTHENTICATED_PER_MINUTE=300`) and **public/pre-auth** (per client IP, `RATE_LIMIT_PUBLIC_PER_MINUTE=30`, covering `/api/auth/google/callback` + `/api/invites/{token}`). Reuses the `rate_limited` error contract; 429 + `Retry-After`. **Fail-open** (a limiter DB error allows). Wired in the lifespan (never in `create_app`), so the DB-less unit tier is never throttled.
- **Session idle-timeout** — `sessions.resolve_owner` now also excludes sessions whose `last_seen_at` is older than `SESSION_IDLE_TIMEOUT_HOURS=336` (14d), making the recorded-but-unchecked `last_seen_at` load-bearing. Absolute `SESSION_TTL_HOURS=720` (30d) unchanged.
- **DB-enforced invite single-use + TTL** — `_consume_invite`'s `UPDATE` now carries the full `WHERE status='pending' AND expires_at > now()` predicate (rowcount==1 gate), so single-use holds at the datastore independently of the row lock.
- **Prompt injection (data-not-instructions)** — the only user/creator-controlled string reaching the model (the platform title via `with_source_context`) is length-capped and wrapped in an explicit "untrusted metadata — NOT instructions" frame. Uploads carry `title=None`.
- **SSRF guard (`chefclaw.netguard`)** — the one non-allowlisted fetch (the Rednote CDN media URL the sidecar returns from note content) is DNS-resolved and refused if it points at a private/loopback/link-local (incl. `169.254.169.254`) address; the media download is byte-capped at `MAX_UPLOAD_MB` and file-count-capped.
- **Stored-XSS guard** — the upload path's free-form `provenance_url` (which becomes the rendered "View original" href) is refused unless http(s) at the boundary; the SPA render guards too (`javascript:`/`data:` never becomes an href).
- **CI dependency audit** — `pip-audit` (backend job) + `npm audit --audit-level=high` (secrets job), both currently zero.
- **Docs** — session-management runbook (`docs/RUNBOOK.md` §6) + the `CHEFCLAW_API_TOKEN`→session cutover timing and session controls (`docs/SECURITY.md`).

## Why

- **Append-only rate events over a mutable counter** (kit pattern, `docs/SECURITY.md`): no row to race, no cron to reset; the per-key advisory-xact-lock closes the count-then-insert TOCTOU, and an opportunistic prune bounds growth. **Fail-open** because a throttle that can wedge the whole app is worse than the abuse it prevents (a real DB outage already 503s from `require_owner`). Rejected an in-memory limiter (the ADR-named deferral) — it works at one worker but doesn't survive a restart and can't be inspected/swept; the DB table is the same lookup substrate M2 already uses.
- **The two HIGH audit findings were fixed, not deferred**, because V2-D *is* "public-exposure readiness": a stored `javascript:` XSS link (upload `provenance_url` → unsanitized `href`) and an SSRF to internal hosts / cloud metadata (sidecar-returned media URL) are exactly what breaks on exposure. Both fixes are contained and testable.
- **Idle-timeout + DB-TTL close the three deferred M2 nice-to-haves** the M2 ADR listed (session idle-timeout, DB-enforced invite single-use, auth-endpoint throttle — the last folds into the public rate-limit bucket).
- **No OpenAPI/route/schema change** — every control is middleware, config, a service-internal predicate, or a table with no API surface — so `openapi.json` + the generated client are byte-identical (drift check green without a regen).

### Accepted residuals (documented, not fixed here)

- **Chunked-upload ASGI byte cap** (pre-named): `Content-Length` + the handler's streaming write-guard backstop it today; a full close needs an ASGI receive-counter. Low risk on a Tailscale-gated single-user box.
- **SSRF redirect chain / DNS-rebinding**: `netguard` re-checks only the initial host; a followed redirect's hops and a name that flips between the guard's resolve and httpx's resolve aren't caught. The direct-internal-URL vector (the realistic one — the sidecar returns the URL directly) is closed. **Must close before any cloud (metadata-service) exposure.**
- **Rate-limit client IP is the direct peer** — a future reverse proxy (Caddy/Traefik for public TLS) needs a trusted-proxy `X-Forwarded-For` read.
- **`oauth_tx` "single-use" is client-cookie-clear only** (no server-side consumption record); mitigated by Google's one-time `code` (a replayed code fails token exchange → opaque 403). Comment wording softened.
- **`GOOGLE_OAUTH` ID-token `exp`** is validated only when present (authlib default); Google always sends it. **No session rotation on privilege change** (not a fixation risk — tokens are server-minted). **Qwen loads the whole video into RAM** (64 MiB guard fires first → denial-of-extraction, not a memory vuln). **`chefclaw_fetch_proxy` creds** could surface in an httpx exception repr → `job.error_detail` (owner-only; proxy ladder not live).
- **No HTTP security headers** (CSP / `X-Content-Type-Options` / `X-Frame-Options` / HSTS) — folded into M4 public-deploy readiness; a CSP would also defense-in-depth the XSS.

### Human-gated (queued for Braeden — not attempted here)

Enable Dependabot + secret-scanning **push protection** (GitHub → Settings → Security); rotate/drop the now-inert `CHEFCLAW_API_TOKEN` on the deployed box (no coordinated rotation — it grants no access post-M2).

## Verified

- **Unit tier** (`uv run pytest -q`, no DB): 389 → **420 passing** (+31). New: `test_netguard.py` (private/loopback/link-local/metadata IPs + non-http rejected, resolver-seamed — no real DNS), `test_ratelimit.py` middleware (public-bucket 429, session-cookie selects the authed bucket, `limit=0` disables, no-limiter = no throttle), `test_prompt_injection.py` (a malicious title is framed untrusted + length-capped + never displaces the task), upload `provenance_url` non-http(s) → 400 before spooling, rednote SSRF refusal (loopback, non-retryable) + byte-cap abort. Frontend: 106 → **108 passing** Vitest (no clickable link for a `javascript:` `source_url`; http(s) still links).
- **Golden tier** (`-m golden`, throwaway PG on 55432): 28 → **31 passing** incl. the new `PostgresRateLimiter` window-independence + prune, session idle-timeout (resolves within window, not after; `0` disables), expired-invite consume → None with no account created, and the migration now creating `request_events`.
- **CI-shape checks green locally**: `ruff`, `pip-audit` (0 vulns), `npm audit` (0), frontend `tsc`/`eslint`/`prettier`, and `openapi.json`+client re-export = no drift.
- **Audit provenance**: three parallel `/security-review` agents (auth/session/invite/authz; sources/worker/repo SSRF+injection+SQL; frontend+infra). No critical; two HIGH (fixed), one MEDIUM DoS (fixed), the rest medium/low/info recorded above. Auth/OAuth/invite/SQL/owner-scoping surfaces verified solid (JWKS+iss+aud+nonce verification, constant-time state, PKCE binding, `safe_next`, sha256-only sessions, instant revocation, invite TOCTOU-safe, enumeration-oracle-free, `is_admin` non-writable, admin routes transport-gated, no IDOR, no secret leakage, prod fail-closed).
