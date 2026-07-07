# M2: real accounts + invite-only signup (OAuth + opaque sessions)

**Date:** 2026-07-07 · **Context:** milestone M2, opening the accounts work under the Path-B multi-user ADR (`2026-07-07-path-b-multi-user-product.md`). Implemented as four stacked PRs; this ADR is the decision record for all four. Grounded in a facet-designer + adversarial-security pass over the real code.

## Decision

M2 replaces the single shared `CHEFCLAW_API_TOKEN` bearer with real per-user identity. Nothing here changes the `require_owner(...) -> uuid.UUID` contract, the single uvicorn worker, or the strictly-serial job worker.

**Auth engine — Authorization-Code + PKCE via Authlib, server-driven, same-origin.** One new runtime dep (`authlib`, server-side only). The api serves the SPA same-origin, so the flow is server redirects + a cookie — no CORS, no token in JS, the SPA never touches Google. `GET /api/auth/google/login` mints state+PKCE+nonce into a 5-min HttpOnly `oauth_tx` cookie and 302s to Google; `GET /api/auth/google/callback` verifies state+ID-token, resolves email/sub, runs the invite/bootstrap gate, mints a session, sets the cookie, 302s to `next`.

**Sessions — server-side opaque tokens in a `sessions` table (stateful, NOT JWT).** Chosen because the substrate already exists (one Postgres, one worker; a session read is the same indexed lookup as today's owner lookup — no Redis), instant revocation is a hard product requirement (owner de-invites/boots friends; logout must kill the session server-side), and there is no signing-secret rotation footgun. The cookie carries `secrets.token_urlsafe(32)` raw; only its `sha256` is stored (`token_hash`). Lookup: `WHERE token_hash = sha256(cookie) AND expires_at > now()`.

**`require_owner` swap is internals-only.** Signature stays `-> uuid.UUID`; every router's `Depends(require_owner)` is byte-identical; `request.state.owner_id` is still set. It stops reading `Authorization: Bearer`, reads the `chefclaw_session` cookie, hashes it, and resolves the owner via a module-level `fetch_session_owner_id(token_hash)` (stubbable like today's `fetch_owner_id`). The `_cached_owner_id` module singleton is **deleted** (it pins one owner per process — a cross-tenant bug under M2), and conftest's `reset_owner_cache` fixture goes with it.

**Fake-first config (CI has no DB, no network).** Two selectors default to `"fake"`, mirroring `CHEFCLAW_EXTRACTOR`: `chefclaw_auth_provider` (fake|google) and `chefclaw_email` (fake|ses). Factories `get_oauth_provider`/`get_email_adapter` mirror `get_extractor` — fake → in-memory; google/ses → construct real, fail closed with `ConfigError` on empty creds; unknown → `ConfigError`. Unit tier: fake `require_owner` short-circuits to a fixed owner id (no cookie/session read), and the golden tier drives the REAL invite gate + session insert through a `FakeOAuthProvider` that only bypasses Google's network call — never the invite gate.

**Schema (this ADR fixes the shape; PR 1 lands it):** `users` gains `email` (NOT NULL UNIQUE, after backfill), `oauth_provider`/`oauth_subject` (nullable; partial-unique `uq_users_oauth_identity` where both NOT NULL), `display_name`, `status` (check `active|disabled`), `is_admin`, and the M3-readiness `monthly_budget_usd`/`max_attempts_per_day` (added-but-unused in M2). New `invites` (email, sha256 `token_hash`, status `pending|accepted|revoked`, `invited_by`/`accepted_user_id`, `expires_at`; partial-unique one pending per email; NO `owner_id` — an invite is an admin/system artifact) and `sessions` (owner FK, sha256 `token_hash` unique, `expires_at`, throttled `last_seen_at`).

**Endpoints (PR 2/3):** auth `login`/`callback`/`logout`/`GET /api/me`, public `GET /api/invites/{token}`; admin `POST /api/admin/invites`, `GET /api/admin/invites`, `POST /api/admin/invites/{id}/revoke`, each behind a transport-layer `require_admin`. Activation happens INSIDE the callback via `consume_invite(...)` in ONE transaction (user create/claim + invite pending→accepted).

**PR sequence (each needs the prior MERGED — stacked, not branched-on-branch):**
- **PR 1 `feat/m2-schema-and-owner-scoped-dedupe`** — schema + two Alembic revisions + owner-scoped dedupe (repo/jobs/fakes) + owner-scoped illustration & retained-media paths + cross-owner regression tests. Nothing user-visible; new tables unused. **← this session.**
- **PR 2 `feat/m2-oauth-sessions`** — oauth providers, `require_owner` internals + `require_admin` + delete `_cached_owner_id` + the prod-env fake guard, auth routers, config auth block, wiring before the SPA catch-all, openapi/client regen.
- **PR 3 `feat/m2-invites-email`** — email adapter package, `services/invites.py` (consume/revoke/list + gated bootstrap-claim), admin router, callback gate wiring, invite errors/schemas, config email block, openapi/client regen.
- **PR 4 `feat/m2-frontend-auth`** — delete the token gate, `credentials:'include'`, drop bearer from OpenAPI, login/invite-accept/admin pages, account menu, Playwright + golden auth seeding.

## Why

- **Opaque stateful sessions over JWT.** Instant server-side revocation is a product requirement (de-invite/boot a friend, logout must kill the session); a signed stateless token can't be revoked without a blocklist that reintroduces the state we'd be avoiding. sha256-at-rest means a leaked DB dump can't be replayed as live cookies. Rejected JWT (revocation + rotation footguns) and a Redis session store (needless second datastore — the single Postgres already indexes this exact lookup shape).
- **Server-driven OAuth, SPA never sees a token.** Same-origin serving lets the whole flow be redirects + an HttpOnly cookie; the SPA does one `useQuery(/api/me)`. Rejected password auth (storage/reset/breach surface) and magic-link (same email infra as invites, weaker than OAuth) per the Path-B ADR.
- **Fake-first defaults keep CI hermetic** (no DB, no network) exactly like the extractor/image seams — but that default is itself a footgun (see M7 below), so it is fenced by a prod-env startup guard rather than trusted.
- **Owner-scoped dedupe is a Path-B pre-commitment come due.** The Path-B ADR flagged the unscoped dedupe (`find_active_job` / `find_completed_job_with_recipes` / `find_recipe_ids` + the `UNIQUE(platform,canonical_id,dish_index)` constraint) as a cross-tenant leak M2 must close. PR 1 closes it, because the schema swap is a one-way door and must land with its consumers.

### Security commitments (this milestone honors every one)

Two decisions are **baked in** (not re-litigated):

- **Bootstrap-claim is gated on a fail-closed `bootstrap_admin_email` setting.** The first-owner bootstrap adopts the seed admin row ONLY if the verified OAuth email equals `bootstrap_admin_email`; empty ⇒ bootstrap-claim is disabled entirely. This kills the "first stranger to sign in becomes admin and inherits Braeden's recipes" race (PR 3).
- **A prod-env startup guard fails the boot closed.** Reuse `sentry_environment` (`local`|`vps`) as the prod signal: when it is `vps`, a fake auth provider OR fake email provider raises `ConfigError` at STARTUP (fail the container boot — never silently auth-bypass). Defaults stay `fake` so CI/dev/golden never reach Google/SES (PR 2).

From the adversarial critique, every MUST-FIX is a requirement this milestone commits to (phase in parens):

- **M1 — illustration file paths are owner-scoped (PR 1).** `illustration_path` gains an `owner_id` segment: `{media_dir}/{owner_id}/{platform}/{canonical_id}/illustration-{dish_index}.jpg`. Two owners extracting the same canonical video no longer overwrite/serve each other's image. Existing single-owner rows keep their absolute `image_url` string (no data migration; only new writes get the segment).
- **M2 — `find_completed_job_with_recipes` scopes BOTH the Recipe probe AND the Job select; retained media (`_retain_media`) gets the same owner segment (PR 1).**
- **M3 — the `oauth_tx` cookie is HttpOnly; Secure; SameSite=Lax; Path=/api/auth; Max-Age=300, single-use** (deleted immediately after read; reject if absent; verify state AND ID-token nonce) (PR 2).
- **M4 — `next` is same-origin-only** (`startswith("/")`, not `//`, no scheme); default `/` on violation (PR 2).
- **M5 — the invite→OAuth match requires `email_verified is True`**, normalizes both sides identically (lowercase+strip, NO gmail dot-stripping), and binds returning users on `(oauth_provider, oauth_subject)` — email-match is only for first activation (PR 3).
- **M6 — non-invited sign-in fails CLOSED with no side effects**: ONE opaque 403, no users row, no session, no "no invite" vs "email mismatch" oracle. Plus the baked-in bootstrap-claim gate (PR 2/3).
- **M7 — the `="fake"` default is defended in depth (PR 2):** (1) the prod-env startup guard above; (2) the fake `require_owner` branch refuses to run if `google_oauth_client_id` is set; (3) unknown selector → `ConfigError`.
- **M8 — session cookie `Secure` is derived from env (prod ⇒ always Secure; no standalone human toggle)**; session-id generation is separate from `oauth_tx`; `last_seen_at` writes are throttled (PR 2).
- **M9 — `require_admin` lives at the TRANSPORT layer** on every `/api/admin/*` route; the frontend `me.is_admin` gate is cosmetic; `is_admin` is never settable via any user-facing write — only migration backfill or the gated bootstrap-claim (PR 3).
- **M10 — after the UNIQUE swap the IntegrityError→adopt path fires only for a same-owner race; the `find_recipe_ids` fallback is owner-scoped.** Regression tests prove two owners store the same `(platform,canonical_id,dish_index)` with no cross-owner IntegrityError (PR 1).
- **M11 — the cross-owner tests seed EXPLICIT distinct named owners (OWNER_A/OWNER_B)** and assert isolation both directions (the fakes' `uuid.uuid4()` default would otherwise mask bugs) (PR 1).
- **M12 — the new public endpoints don't set `request.state.owner_id`**; the request-log middleware already reads it via `getattr(..., None)`, so pre-auth requests log cleanly (verified in PR 2).
- **M13 — `GET /api/invites/{token}` is public**: query by indexed `token_hash`; a missing token and a present-but-expired/revoked token return the SAME shape; never return `email` for a non-`pending` status (PR 3).

Accepted tradeoffs / deferred hardening: per-user budget columns are added-but-unused in M2 — `spend.check_budget` still reads the GLOBAL env budget, so all users share one budget pool until M3. `chefclaw_api_token` stays through the deploy window but the bearer branch is a HARD cutover at PR 2/4 (no dual bearer-or-session acceptance; drop `HTTPBearer` from the OpenAPI security scheme). Nice-to-haves tracked for their phase: DB-enforced invite TTL+single-use (`WHERE status='pending' AND expires_at > now()`, rowcount==1), session idle-timeout, and an in-process rate-limiter on the public callback/invite-accept endpoints (cheap at one worker).

## Verified

Direction-and-shape ADR; per-PR verification lands with each PR. PR 1's proof (this session): the cross-owner regression tests seed OWNER_A and OWNER_B with the SAME `(platform, canonical_id)` and assert (a) each `find_active_job`/`find_completed_job_with_recipes`/`find_recipe_ids` returns only its own owner's rows, and (b) both `store_results` succeed against the swapped `UNIQUE(owner_id, platform, canonical_id, dish_index)` with no IntegrityError — run against a throwaway PG18 (`-m golden`), plus a golden check that the two Alembic revisions apply on top of a seeded single-owner DB and backfill it (`email='owner@localhost'`, `is_admin=true`). The unit tier (`uv run pytest -q`, no DB) proves the fakes mirror the owner-scoped seam. rev2 documents the one-way door: once a real second user exists, downgrading to the 3-column constraint would violate it.
