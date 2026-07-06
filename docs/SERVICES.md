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
| Host env (deployed) | Does not exist until M-Deploy; re-map then | — |

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
  daily-cap check before every paid call.
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
  daily via `ops/com.chefclaw.backup.plist.example`. Full procedures, install
  steps, restore, and the performed drill record: `docs/RUNBOOK.md` §2.
- **Secret + which store:** `BACKUP_GPG_PASSPHRASE` — **canonical copy in the
  password manager** (generated once, stored there FIRST — never only on this
  machine); `.env.local` holds the operational copy the script resolves at
  runtime. Staleness is surfaced by `/api/health` (`fresh`/`stale`/`not_configured`).
- **Provisioning record:** 2026-07-06 — script + launchd example landed; **restore
  drill performed and verified** (row counts, content checksums, media SHA-256
  round-trip — record in `docs/RUNBOOK.md`). launchd agent **not yet loaded**
  (human step); health reports `not_configured` until scheduled backups run.

## Deferred hardening (tracked here so it can't fall through the cracks)

| Item | Trigger |
|---|---|
| Switch Gemini to **paid tier** (no training) | Before any personal data (M5/M7) — hard precondition |
| `CHEFCLAW_API_TOKEN` rotation + real TLS | When the stack goes public-internet-facing (M-Deploy; Tailscale-only exposure defers it) |
| Per-user budgets / auth beyond bearer token | Multi-user, if it ever happens (dedicated ADR) |
| XHS tier-1 throwaway signup | Only if guest tier stops covering needed notes; main-account fallback is **revoked** (2026-07-06) — tier-2 manual upload is the guaranteed floor |
| DashScope region/data-governance review | Before the fallback adapter's first real call |
