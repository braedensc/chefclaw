# SERVICES.md — external services, keys, and provisioning

Per service: what it is, how we authenticate, where config lives as code, which store
holds which key, the human dashboard steps ("(you, in dashboards)" — Claude cannot and
should not do them), and a dated provisioning record. Deferred hardening at the bottom.

## The stores, adapted for a self-hosted compose app

The kit's three-stores model (docs/SECURITY.md) assumes a cloud host. chefclaw runs as
local Docker compose, so the "host env" store **collapses into `.env.local`**:

| Store | Holds | Set by |
|---|---|---|
| `.env.local` (gitignored) | Everything: `CHEFCLAW_API_TOKEN`, `GEMINI_API_KEY`, `DASHSCOPE_API_KEY` (Phase 4 fallback), `XHS_COOKIE` + `XHS_USER_AGENT` + `XHS_COOKIE_SET_DATE`, `BILIBILI_COOKIE` (optional), `DATABASE_URL`, budget knobs, `MEDIA_RETENTION`, backup knobs (`CHEFCLAW_BACKUP_DIR`, `BACKUP_GPG_PASSPHRASE` — operational copy only) | **Human only** — the hook blocks Claude writing `.env*` |
| Password manager | `BACKUP_GPG_PASSPHRASE` — the **canonical** copy (generated once, stored here FIRST; never only on this machine). `.env.local` carries just the operational copy `scripts/backup.sh` reads | Human only |
| GitHub Actions secrets | **Nothing.** CI runs on dummy env values only; currently no real key needed (revisit at M-Deploy) | — |
| Host env (deployed) | At M-Deploy this becomes the VPS's own `/opt/chefclaw/.env.local` (same human-only rule; var list in `docs/RUNBOOK.md` §4 step 5) — see §7 | Human only |

`.env.example` (placeholders only) is the committed contract. `CHEFCLAW_API_TOKEN` is a
server secret at birth: never a `VITE_*` var, never in the frontend bundle.

## 1. GitHub — `braedensc/chefclaw`

- **Identity:** public repo, AGPL-3.0-or-later (kit files MIT-credited in `NOTICE`).
- **Auth:** `gh` CLI with the human's keychain token. Claude opens PRs; never merges.
- **Config as code:** `.github/workflows/ci.yml`, `docs/examples/protection.json`.
- **Security features** (free on public) — *(you, in dashboards)*: Settings → Security
  (Code security and analysis) → enable **Secret scanning**, **Push protection**, and
  **Dependabot** (alerts + security updates).
- **Branch protection:** apply `docs/examples/protection.json` to `main` with only the
  Phase-0 context `Secret scan + forbidden paths`. After Phase 1's jobs (Lint,
  Typecheck, Test, backend lint/test, drift check) first report green on `main`, POST
  the updated context list — merge-then-require (docs/LESSONS.md).
- **Provisioning record:** 2026-07-05 — repo created from `braedensc/claude-project-kit`
  template. Secret scanning / push protection / Dependabot: **pending** (enable at
  bootstrap-PR time). Branch protection: **pending** (Phase-0 context only; extend
  after Phase 1).

## 2. Google Gemini API (primary extractor)

- **Identity:** Google AI Studio API key; used server-side by the worker only
  (Gemini 2.5 Flash via Files API, thinking disabled; model id is a config string).
- **Auth:** `GEMINI_API_KEY` — lives in `.env.local` only. Never in CI, never client-side.
- **Privacy — load-bearing:** the **free tier is training-eligible**. Acceptable for
  public cooking videos only. **Switching to the paid tier is a stated precondition
  before any personal data flows through this adapter (M5 nutrition / M7 fitness).**
- **Cost:** fail-closed budget guardrails — `MONTHLY_LLM_BUDGET_USD` /
  `MAX_EXTRACTION_ATTEMPTS_PER_DAY` unset or unparseable ⇒ no paid calls (typed config
  error); `llm_spend` ledger written per model attempt including failures; budget +
  daily-cap check before every paid call. Per-user caps override the global defaults
  when set (M3, `docs/adr/2026-07-07-per-user-budget-caps.md`).
- **Model quality tier (M3 — distinct from the data/billing tier above):**
  `GEMINI_MODEL` is the *model* everyone runs by default (`gemini-2.5-flash`, cheap).
  `GEMINI_PAID_MODEL` (`gemini-2.5-pro`) buys higher extraction quality at ~4x input /
  ~3x output token cost (both priced, padded, in `chefclaw.spend.GEMINI_PRICING`, so the
  same fail-closed budget gate bounds pro spend — no new guardrail). Two ways to enable
  it: flip `GEMINI_MODEL` itself (**global** — everyone), or set a specific account's
  `users.paid_tier` via `PATCH /api/admin/users/{id}/budget` (**per-user** — that
  account's extractions use `GEMINI_PAID_MODEL`). The swap lives once in
  `extractors.extractor_settings_for_tier` and is scoped to extraction only (cover
  illustration stays global).
- **Provisioning** *(you, in dashboards)*: aistudio.google.com → sign in → "Get API
  key" → create key → paste into `.env.local`.
- **Provisioning record:** 2026-07-05 — **not yet provisioned** (lands with Phase 2).

## 3. DashScope / Qwen (fallback extractor)

- **Status: implemented, UNVERIFIED-LIVE** (Phase 4) — `QwenExtractor` behind
  `CHEFCLAW_EXTRACTOR=qwen` (+ `DASHSCOPE_MODEL`, `DASHSCOPE_BASE_URL`), built
  against the documented OpenAI-compatible video-input shape and fail-closed
  when keyless; it has **never been exercised against the live endpoint** (no
  key exists). Known-unverified specifics are marked in
  `backend/src/chefclaw/extractors/qwen.py` (Base64 video acceptance + size
  cap, current model catalog).
- **Precondition before first use (HUMAN):** review the endpoint's **region and
  data-governance terms** (where video bytes land, retention, training
  eligibility), pick the base URL deliberately, and note the result here.
- **Provisioning** *(you, in dashboards — only AFTER the region review above)*:
  DashScope console → create an API key → paste into `.env.local` as
  `DASHSCOPE_API_KEY` (optionally `DASHSCOPE_MODEL` / `DASHSCOPE_BASE_URL`), then
  restart the api with `CHEFCLAW_EXTRACTOR=qwen` to switch over.
- **Provisioning record:** 2026-07-05 — not provisioned. 2026-07-06 — adapter
  landed (mocked tests only); key still not created; region review still pending.

## 4. Rednote / Xiaohongshu (via XHS-Downloader sidecar)

- **Access is tiered** (policy 2026-07-06; supersedes the 2026-07-05
  throwaway-account decision). **The main account NEVER enters the pipeline under any
  circumstances** — no cookie, no session, no fallback-to-main:
  - **Tier 0 — guest (DEFAULT, verified 2026-07-06):** no account at all — a real
    public note fetched with no cookie. While guest covers typical cooking posts, no
    account ever touches the pipeline.
  - **Tier 1 — hard-isolated throwaway** (only for content guest can't fetch):
    signed up with a different phone number, used **web-only in a dedicated browser
    profile** that has never seen the main account, never installed in the phone app
    beside it. A ban of it is disposable.
  - **Tier 2 — manual file upload** (`LocalFileSource`): zero-platform-risk floor;
    extraction never *requires* platform access.
- **Auth (tier 1 only):** session **cookie + matching User-Agent pair** —
  `XHS_COOKIE`, `XHS_USER_AGENT` in `.env.local`. **Cookies are session credentials =
  key-grade secrets**, guarded in every layer (PreToolUse hook, native deny,
  `.gitignore`, pre-commit grep, CI grep, secretlint value-pattern rules). The cookie
  rides **per-request** in the api's sidecar call — the sidecar stays stateless; no
  config-file cookie mount.
- **Share links required:** XHS rejects token-less URLs, so paste the **full share
  link** — its `xsec_token` is preserved on the fetch URL only; the canonical note id
  stays token-free for dedupe (see the 2026-07-06 adapters ADR).
- **Expiry:** 2–4 weeks. `XHS_COOKIE_SET_DATE` is written by hand at **every** refresh
  (age is not derivable from the cookie string); `/api/health` warns before expiry.
  Refresh procedure: `docs/RUNBOOK.md` §1 (tier 1 only — never the main account).
- **Isolation:** sidecar runs on the **internal compose network only — no published
  host port** (its API is unauthenticated); image pinned to digest
  `sha256:7ce9c4e7711b7a805da5b1d4190079ad0eaf4abf07f235fe8b90c8da51b8c823`
  (v2.7.stable). The sidecar response echoes the cookie in its `params` field —
  **never log raw sidecar response bodies**; the adapter parses `data` only.
- **ToS reality, stated plainly:** automated downloading violates platform ToS. Posture
  is personal use — single user, built-in delays, no redistribution.
- **Provisioning record:** 2026-07-05 — account not created; Phase 2 setup step.
  2026-07-06 — guest tier verified against a real public note; **no account created**
  (tier-0 default holds; tier-1 signup only if guest stops sufficing).

## 5. Bilibili (via yt-dlp)

- **Identity/auth:** **anonymous-first** — no account, no cookie; yt-dlp's 480p
  anonymous cap is fine for LLM extraction. Optional `BILIBILI_COOKIE` (free account,
  `.env.local`) only if on-screen-text OCR ever needs 1080p.
- Same ToS posture as §4: personal use, low volume, delays, no redistribution.
- **Provisioning record:** 2026-07-05 — nothing to provision.

## 6. Backups (local gpg + launchd — no external service)

- **Identity:** `scripts/backup.sh` — read-only encrypted `pg_dump` + media-volume
  archive to `CHEFCLAW_BACKUP_DIR` (e.g. `<your-backup-destination>`), scheduled
  daily via `ops/com.chefclaw.backup.plist.example` (macOS/launchd; on the VPS:
  the systemd units — §7). Full procedures, install
  steps, restore, and the performed drill record: `docs/RUNBOOK.md` §2.
- **Secret + which store:** `BACKUP_GPG_PASSPHRASE` — **canonical copy in the
  password manager** (generated once, stored there FIRST — never only on this
  machine); `.env.local` holds the operational copy the script resolves at
  runtime. Staleness is surfaced by `/api/health` (`fresh`/`stale`/`not_configured`).
- **Provisioning record:** 2026-07-06 — script + launchd example landed; **restore
  drill performed and verified** (row counts, content checksums, media SHA-256
  round-trip — record in `docs/RUNBOOK.md`). launchd agent **not yet loaded**
  (human step); health reports `not_configured` until scheduled backups run.

## 7. M-Deploy — VPS (public TLS at M4; prep landed; provisioning pending)

- **Posture** (ADR `docs/adr/2026-07-06-m-deploy-vps-and-rednote-escalation.md`,
  incl. its **M4 amendment**): ≥2 GB Ubuntu LTS x86 VPS, ports stay
  `127.0.0.1`-bound. **M4 = public TLS** — a Caddy reverse proxy terminates HTTPS
  on a real domain in front of `127.0.0.1:8000` (80/443 public, 8000/5432
  loopback); **auth is the boundary** (Google OAuth + sessions, M2). This
  **supersedes the V2-B Tailscale-private endgame** for the product;
  `tailscale serve` stays the interim/dev/personal path. Ordered human steps +
  go/no-go gates: `docs/DEPLOY_CHECKLIST.md`. Turn-key procedure: `docs/RUNBOOK.md`
  §4; Rednote escalation playbook (self-host/interim only): §5.
- **Domain + DNS (public path)** *(you, at a registrar)*: register a domain, add
  an A (and AAAA if IPv6) record → the VPS public IP, propagated before Caddy's
  first cert issuance. Record domain + registrar here.
- **Google OAuth client (M2/M4)** *(you, Google Cloud Console)*: OAuth 2.0 Web
  client with authorized redirect `https://<domain>/api/auth/google/callback`.
  Client id → `.env.local`; the **secret is server-only** (never `VITE_*`).
- **Transactional email — AWS SES (or Resend)** *(you, dashboards)*: verified
  sender, out of the SES sandbox for external invitees; `EMAIL_FROM` + `SES_REGION`
  → `.env.local`; SES send creds via the instance IAM role.
- **VPS (Hetzner-class)** *(you, in dashboards)*: Hetzner Cloud → CX-class
  server, Ubuntu LTS, SSH-key-only auth. The server's
  `/opt/chefclaw/.env.local` is the deployed host-env store (human-only, same
  as locally; exact var list in RUNBOOK §4 step 5 — `CHEFCLAW_API_TOKEN` gets
  a **fresh** token, never the local dev one).
- **Caddy (public path)** *(you, on the VPS)*: host-service reverse proxy,
  auto-renewed Let's Encrypt cert (RUNBOOK §4 step 7 Option A). **Tailscale
  (interim path)** *(you, in dashboards)*: create/sign in to the tailnet, approve
  the VPS from `tailscale up`'s auth URL, enable HTTPS certificates when
  `tailscale serve` asks, install the phone app on the same tailnet.
- **Backups on the VPS:** scheduled via the systemd units
  (`ops/chefclaw-backup.service.example` + `.timer.example`);
  `CHEFCLAW_BACKUP_DIR` must point **off-VPS** (tailnet copy home or object
  storage — decide at provisioning; the artifacts are gpg-encrypted at rest).
- **Provisioning record:** 2026-07-06 — VPS/Tailscale prep landed (fetch-proxy
  knob, systemd unit examples, RUNBOOK §4/§5, ADR). 2026-07-07 — **M4 public-TLS
  prep landed** (RUNBOOK §4 Caddy path + multi-arch note, `docs/DEPLOY_CHECKLIST.md`,
  session-aware `prod-smoke.sh`, `.env.example` auth block, ADR M4 amendment).
  **All account/secret provisioning pending** (record dates/choices here when
  done): **VPS** (server type, region), **domain + registrar**, **Google OAuth
  client**, **SES sender + region + sandbox status**, **off-VPS backup
  destination**, **Tailscale tailnet** (if using the interim path). First
  rednote-from-datacenter test result: **pending deploy day** (self-host/interim
  only — the public product is upload-only).

## 8. Sentry (error tracking — V2-A, DSN-gated)

**What it is, plainly:** a hosted error-tracking service. When the backend
worker or the SPA hits an unhandled error, the SDK sends a report (stack
trace, tags like job id/stage/error_type, release SHA) to sentry.io, which
groups duplicates into "issues" and can email on new ones. Without it, a job
that dies on the VPS is just a log line nobody was watching.

- **Cost:** the free Developer tier (generous event quota, 30-day retention,
  one user) — chefclaw's single-user error volume is a rounding error against
  it. No card required, no paid tier ever needed for this project.
- **Provisioning** *(you, in dashboards)*: create a free account → one project
  (platform: Python) → copy its **DSN** into `.env.local` as `SENTRY_DSN` and
  `VITE_SENTRY_DSN` (one project for both is fine at this volume; split into a
  second React project later if the mixed stream annoys). Set
  `SENTRY_ENVIRONMENT=vps` on the server, leave `local` elsewhere.
- **DSN posture:** a DSN is an ingest ADDRESS, not a credential — someone with
  it could send you fake events, not read anything. It may be baked into the
  public SPA bundle (`VITE_SENTRY_DSN`); it still lives in `.env.local`, and
  Hard Rule 4 (server keys never as `VITE_*`) is unaffected.
- **`VITE_SENTRY_DSN` is baked at CI BUILD time under push-based CD.** Since the
  push-based deploy (RUNBOOK §4 "Continuous deployment"), the SPA's DSN is passed
  as a build-arg from a GitHub Actions **repository variable** (`vars.VITE_SENTRY_DSN`
  — public, `vars.` not `secrets.`) and compiled into the public bundle by CI; the
  box's `.env.local` `VITE_SENTRY_DSN` now matters only for a local/manual `up -d
  --build`. The **backend** runtime `SENTRY_DSN` is unchanged — still read from
  `.env.local` on the box. Server keys are never build-args.
- **Gating (kit pattern):** empty/unset DSN ⇒ the SDK is **never initialised**
  — dev, CI, and tests send zero events by construction. Proven by unit test
  (`backend/tests/test_observability.py`, `frontend/src/sentry.test.ts`).
- **What gets sent / scrubbed:** error tracking only (no tracing, no session
  replay, no PII, request bodies never); an event scrubber additionally
  denylists every chefclaw secret name (cookies, API keys, the bearer token).
- **Sentry MCP:** the tooling has a Sentry MCP server wired for inspecting
  issues from Claude sessions — needs one-time OAuth (claude.ai connector
  settings, or `/mcp` in an interactive `claude` session).
- **Provisioning record:** 2026-07-06 — code landed DSN-gated (V2-A PR).
  **Sentry project: pending creation** (record date + org/project slug here);
  MCP auth: pending.

## Deferred hardening (tracked here so it can't fall through the cracks)

| Item | Trigger |
|---|---|
| Switch Gemini to **paid tier** (no training) | Before any personal data (M5/M7) — hard precondition |
| `CHEFCLAW_API_TOKEN` rotation + real TLS | When the stack goes public-internet-facing (M-Deploy; Tailscale-only exposure defers it) |
| Per-user budgets / auth beyond bearer token | Multi-user, if it ever happens (dedicated ADR) |
| XHS tier-1 throwaway signup | Only if guest tier stops covering needed notes; main-account fallback is **revoked** (2026-07-06) — tier-2 manual upload is the guaranteed floor |
| DashScope region/data-governance review | Before the fallback adapter's first real call |
| Bound `MAX_UPLOAD_MB` for **Content-Length-less (chunked)** uploads at the ASGI layer | V2-D audit — the pre-parse Content-Length middleware + the handler streaming guard already close the realistic case (all browser/mobile uploads send Content-Length); the residual is a token-holder using a custom chunked client on a Tailscale-gated single-user box |
