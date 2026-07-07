# Architecture

chefclaw: paste a Bilibili or Rednote cooking-video link → async extraction
pipeline → structured bilingual recipe in a browsable library. Single user now,
deploy-ready by design. Four rules shape every layer:

1. **The API is the product; the UI is a client.** The REST/OpenAPI surface is
   the stable contract. The SPA is its first client; an MCP server and mobile
   arrive later as further clients of the same API.
2. **Framework-free service layer.** All business logic lives in plain Python
   services. FastAPI routers are one thin transport (parse/validate/serialize
   only); no logic in routers or React.
3. **Everything external is an adapter.** Video sources (`SourceAdapter`),
   extraction models (`ExtractorAdapter`), and later nutrition/fitness/price
   providers sit behind small, documented interfaces. Adding a platform is a
   new adapter, not a refactor.
4. **Anything slow is an async job.** Extraction takes minutes; requests never
   block on it. A `jobs` table in Postgres claimed with `FOR UPDATE SKIP
   LOCKED`, executed strictly serially by an in-process worker — no broker.

Plus the product invariant (CLAUDE.md Hard Rule): **never fabricate food data**
— quantities captured verbatim from the source; estimated or derived values
live in separate, explicitly-flagged fields and never overwrite raw captures.

Decisions are recorded as ADRs in `docs/adr/` — one file per decision, named
`YYYY-MM-DD-short-slug.md`, no sequence numbers (convention:
[docs/adr/README.md](adr/README.md)). This table is the index; adding an ADR
adds one row here.

## Index

| ADR | Date | Decision |
|---|---|---|
| [MVP stack & layout](adr/2026-07-05-mvp-stack-and-layout.md) | 2026-07-05 | Python 3.13 + FastAPI + Postgres 18; no-broker single-worker async jobs; Vite + React SPA served same-origin; npm-workspaces monorepo; exact-pins policy |
| [AGPL licensing & kit attribution](adr/2026-07-05-agpl-licensing-and-kit-attribution.md) | 2026-07-05 | AGPL-3.0-or-later (dual-license optionality, sole copyright holder); kit's MIT license preserved in NOTICE |
| [Source & extractor adapter contracts](adr/2026-07-06-source-and-extractor-adapters.md) | 2026-07-06 | `SourceAdapter` resolve → `CanonicalRef` as the authoritative dedupe input; rednote guest-tier default + accepted `xsec_token` fetch-url deviation; digest-pinned internal-only XHS sidecar with per-request cookie; extractor never repairs output; fakes config-selectable |
| [Jobs without a broker](adr/2026-07-06-jobs-without-broker.md) | 2026-07-06 | In-process asyncio worker (one uvicorn worker, strictly serial — double-spend closed at concurrency 1); `FOR UPDATE SKIP LOCKED` claim with attempts counted at claim; idempotent paid stage + fail-closed budget gate before every paid call + per-attempt spend ledger; startup reconcile to `interrupted` (never auto-rerun paid work); atomic N-recipe store; TaskIQ as graduation path |
| [Data model & dedupe on canonical identity](adr/2026-07-06-data-model-and-dedupe.md) | 2026-07-06 | `UNIQUE(platform, canonical_id, dish_index)` as THE dedupe constraint (canonical identity, never raw URLs); `owner_id` + uuidv7 pks from migration #1; jobs carry queryable platform/canonical_id + payload `url`/`fetch_url` (retries never re-resolve); `llm_spend` per attempt as cost/cap source of truth; hard DELETE re-opens extraction; `document` JSONB never user-editable |
| [M-Deploy: VPS + Tailscale & the Rednote escalation ladder](adr/2026-07-06-m-deploy-vps-and-rednote-escalation.md) | 2026-07-06 | Hetzner-class VPS, Tailscale-first, zero public exposure (127.0.0.1-bound ports + `tailscale serve`); MacBook is not a server; rednote-from-datacenter test-first with a prepared all-config escalation ladder (phone upload → home exit node → residential proxy → home relay) behind the single `CHEFCLAW_FETCH_PROXY` knob; backups move to systemd on the VPS and must land off-VPS |
| [V2-A: Observability & cost management](adr/2026-07-06-observability-and-cost.md) | 2026-07-06 | Sentry DSN-gated (no DSN ⇒ no-op; worker failures are the priority events, tagged job/stage/error_type); structured JSON logs on stdlib logging + request/job-lifecycle middleware (never secrets, never sidecar bodies); `GET /api/spend` per-day/per-model breakdown; real budget caps surfaced via `/api/health` (null = fail-closed); 80%/100% crossing-edge budget alerts; worker aliveness = task-not-done |
| [Design system & brand](adr/2026-07-06-design-system-and-brand.md) | 2026-07-06 | Neon night-market direction (bake-off-picked) as Tailwind v4 `@theme` tokens; claw-family puppy-chef mascot; generated cartoon dish covers (Gemini image model, text-only prompt so they're cross-servable; fake-by-default, fail-closed budget-gated, best-effort after the store; served owner-scoped via `has_image` + authed `/image`); `MEDIA_RETENTION` default → `discard`; two derived 0–3 estimates (spiciness/difficulty) in a separate flagged column per Hard Rule 7; restyle strictly inside the golden-selector contract; reduced-motion-guarded animation |
| [Path B: hosted multi-user product (upload-only)](adr/2026-07-07-path-b-multi-user-product.md) | 2026-07-07 | chefclaw pivots to a hosted MULTI-USER product, invite-only (friends-first); the HOSTED service is UPLOAD-ONLY (users bring their own videos — the server never fetches Bilibili/Rednote; link-paste stays self-host-only); social OAuth + owner-sent invite-only signup; phased M1 decision → M2 accounts/invites → M3 per-user caps + paid Gemini → M4 public deploy; TaskIQ concurrency + payments deferred; records two correctness pre-commitments (owner-scope dedupe; move the double-spend gate into the claim tx before a 2nd worker) |
| [Owner-editable estimates & merge posture](adr/2026-07-07-owner-editable.md) | 2026-07-07 | The two derived 0–3 estimates join the `RecipePatch` whitelist (tags/notes); a correction flags the whole `estimated` object `source="user"` (one provenance for the pair, never collapsed to null on clear) and takes precedence over any future re-derivation; extraction stays `source="derived"` (model-supplied `source` stripped); 0–3 `strict` int validation (no bool/float coercion); API exposes read-only `estimated_source` so the UI drops the "(estimated)" flag once overridden; `document` JSONB still never editable |
| [Illustration generation is its own retriable job](adr/2026-07-07-illustration-job-type.md) | 2026-07-07 | Promote the post-store cover-illustration stage to a first-class `illustration` job type (new `illustrating` status; null platform/canonical_id; one per recipe); the extraction store enqueues them and the startup backfill enqueues instead of generating inline, so image gen has ONE serial execution path; `POST /api/recipes/{id}/illustration` (owner-scoped, `jsonb_exists` per-recipe dedupe) powers both the drawer Retry and a detail-page Regenerate; fake-by-default + fail-closed budget gate + per-image ledger unchanged; reconcile owns a stranded `illustrating` job |
| [Cover system: curated sprites + private real-frame covers](adr/2026-07-07-cover-system-sprites-and-private-frames.md) | 2026-07-07 | Two layered cover modes gated so only the legally-clean one can reach others: `sprite` (274 original neon SVGs, the new DEFAULT — assigned by folding a `cover_sprite_id` pick into the extraction Gemini call with a deterministic keyword-match fallback, rendered INLINE from the bundled asset, `unknown-dish` final fallback, low-confidence misses logged to a new `cover_misses` table for a future PR-gated "cover gardener"; no illustration job, zero paid image call) demotes the generated-Gemini cover to an optional mode; `video_frame` (PRIVATE) grabs one finished-dish beauty-shot frame via ffmpeg from the Gemini-returned timestamp during extraction (fits `MEDIA_RETENTION=discard`), double-gated by a global `CHEFCLAW_REAL_COVERS` + per-user owner-set `real_covers_enabled` (both default OFF) with viewer-aware `has_image`/`/image` so a frame never reaches an ungranted viewer; one migration off `e2f3a4b5c6d7` |
| [Extractor robustness QA: image notes + resolution escalation](adr/2026-07-07-extractor-robustness-qa.md) | 2026-07-07 | Rednote image notes (图文) fast-fail typed (`image_note_unsupported`, not retryable) from the sidecar's `作品类型` BEFORE any media download or paid call (option a; multi-image→vision deferred); opt-in one-shot media-resolution escalation via `GEMINI_MEDIA_RESOLUTION_MAX` (empty = OFF, v4 unchanged) — a v5 envelope prompt's `capture_quality` self-report triggers a single higher-res retry of the same uploaded video with summed usage (accepted: that 2nd call skips the worker budget gate — bounded/opt-in); every `error_type` gets actionable jobs-drawer copy; a `prep_state`-only prompt tightening; `docs/QA_MATRIX.md` real-video matrix (Run 1) |
| [M2: real accounts + invite-only signup](adr/2026-07-07-m2-accounts-and-invites.md) | 2026-07-07 | Replace the shared bearer with per-user identity: server-driven Google OAuth (Authorization-Code + PKCE via Authlib, same-origin, SPA never sees a token) + opaque server-side `sessions` (sha256-at-rest, instant revocation, NOT JWT); `require_owner` swap is internals-only (`_cached_owner_id` deleted); invite-only signup gated in the callback (`invites` table, transactional-email adapter, admin invite endpoints behind transport-layer `require_admin`); fake-first `chefclaw_auth_provider`/`chefclaw_email` selectors fenced by a `vps` startup guard; bootstrap-claim gated on `bootstrap_admin_email`; owner-scoped dedupe + illustration/retained-media paths + `UNIQUE(owner_id,platform,canonical_id,dish_index)` land in PR 1; four stacked PRs; commits to critique M1–M13 |
| [V2-C cross-device: mobile-responsive pass + installable PWA](adr/2026-07-07-v2c-cross-device.md) | 2026-07-07 | Responsive audit of every screen at a 375 px floor inside the existing neon design system (apply, don't restyle); ≥44 px touch targets gated to `(pointer: coarse)` via `tap-target`/`tap-field` utilities so desktop stays pixel-identical; jobs drawer → bottom sheet on mobile / right sidebar at `≥sm` (same `<aside aria-label="Jobs">`, reduced-motion-guarded); dependency-free manual service worker (app-shell network-first, hashed assets cache-first, **`/api/*` never cached**) + hand-written manifest with maskable/apple-touch icons from the puppy-chef mark; prod-only uncontrolled-first-load SW registration; phone-viewport (Pixel 5) Playwright project added to the LOCAL-ONLY golden suite |
| [V2-D: Security audit + public-exposure readiness](adr/2026-07-07-security-audit-v2.md) | 2026-07-07 | Formal `/security-review` pass (multi-agent, no criticals; 2 HIGH + 1 MEDIUM fixed). Adds API rate limiting (`request_events` append-only, per-session + per-IP trailing-window, fail-open, reuses `rate_limited`); session idle-timeout (makes `last_seen_at` load-bearing); DB-enforced invite single-use+TTL; SSRF guard on the sidecar-returned Rednote media URL + byte cap; upload `provenance_url` http(s)-only (stored-XSS) + SPA href guard; prompt-injection framing/length-cap on the source title; `pip-audit`+`npm audit` in CI (zero). Closes the three deferred M2 nice-to-haves. Residuals recorded (chunked-upload ASGI cap, SSRF redirect-chain/rebinding, proxy XFF, security headers→M4); Dependabot/push-protection + token drop human-gated. No route/schema change (no OpenAPI drift) |

## Planned ADRs

Reserved here so deferrals stay decisions, not accidents. Each is written when
its phase or milestone opens, with a design pass over
`planning/chefclaw-plan.md` (gitignored reference) first.

**Phase 2 — extraction pipeline:**

- **Adapter contracts, sidecar isolation & extractor config** — **done**:
  [Source & extractor adapter contracts](adr/2026-07-06-source-and-extractor-adapters.md)
  (2026-07-06) covers the `SourceAdapter`/`ExtractorAdapter` interfaces,
  canonical-id resolution, rednote tiered access, the digest-pinned
  internal-only XHS sidecar, and the Gemini extractor settings.
  DashScope/Qwen fallback and the degraded ASR+OCR roadmap keep their Phase-4
  slot (docs/SERVICES.md §3).
- **Jobs without a broker** — **done**:
  [Jobs without a broker](adr/2026-07-06-jobs-without-broker.md) (2026-07-06)
  covers the full worker semantics as shipped — idempotent paid stage,
  attempt caps, startup reconcile, fail-closed budget guardrails, the
  per-attempt spend ledger, the atomic N-recipe store, the two hard
  constraints (one uvicorn worker, strictly serial execution), and the TaskIQ
  graduation path. Process-group kill stays a noted follow-up there
  (cooperative thread cancellation is the accepted tradeoff).
- **Data-model shape** — **done**:
  [Data model & dedupe on canonical identity](adr/2026-07-06-data-model-and-dedupe.md)
  (2026-07-06) covers recipes/jobs/llm_spend as exercised, dedupe on
  canonical identity via `UNIQUE(platform, canonical_id, dish_index)`, the
  job payload's `url`/`fetch_url` split, hard-delete-reopens-extraction, and
  the never-user-editable JSONB document.

**Future — explicitly reserved:**

- **Re-extraction semantics** — what happens when a stored recipe's source is
  extracted again (prompt v2, resolution escalation, model swap). Deferred at
  MVP (DELETE is a hard delete; a duplicate paste returns the existing job);
  this entry exists so the deferral cannot fall through the cracks. Must
  address stale rednote `xsec_token` fetch_urls (tokens expire, so
  re-extraction may need a fresh share link — see the 2026-07-06 adapters
  ADR's accepted tradeoffs) and the partial multi-dish delete quirk
  (deleting one of N sibling recipes leaves the rest, so dedupe still
  returns the stored job and the deleted dish is not re-extractable — see
  the 2026-07-06 data-model ADR's accepted tradeoffs).

**Milestones — each opens with its own ADR:**
M-Deploy — **done**:
[M-Deploy: VPS + Tailscale & the Rednote escalation ladder](adr/2026-07-06-m-deploy-vps-and-rednote-escalation.md)
(2026-07-06; prep PR — deploy-day execution follows `docs/RUNBOOK.md` §4) ·
M5 nutrition · M6 meal planning + grocery · M7 fitness ingestion ·
M8 MCP server · M9 mobile.
