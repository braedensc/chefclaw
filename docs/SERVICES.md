# SERVICES.md — external services, keys, and provisioning

Per service: what it is, how we authenticate, where config lives as code, which store
holds which key, the human dashboard steps ("(you, in dashboards)" — Claude cannot and
should not do them), and a dated provisioning record. Deferred hardening at the bottom.

## The stores, adapted for a self-hosted compose app

The kit's three-stores model (docs/SECURITY.md) assumes a cloud host. chefclaw runs as
local Docker compose, so the "host env" store **collapses into `.env.local`**:

| Store | Holds | Set by |
|---|---|---|
| `.env.local` (gitignored) | Everything: `CHEFCLAW_API_TOKEN`, `GEMINI_API_KEY`, `DASHSCOPE_API_KEY` (later), `XHS_COOKIE` + `XHS_USER_AGENT` + `XHS_COOKIE_SET_DATE`, `BILIBILI_COOKIE` (optional), `DATABASE_URL`, budget knobs, `MEDIA_RETENTION` | **Human only** — the hook blocks Claude writing `.env*` |
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

- **Status: deferred** — implemented as a config-flagged `ExtractorAdapter` in Phase 4;
  key (`DASHSCOPE_API_KEY`, `.env.local`) not created until then.
- **Precondition before first use:** review the endpoint's **region and
  data-governance terms** (where video bytes land, retention, training eligibility)
  and note the result here.
- **Provisioning record:** 2026-07-05 — not provisioned.

## 4. Rednote / Xiaohongshu (via XHS-Downloader sidecar)

- **Identity:** a **secondary throwaway account** (decided 2026-07-05), created during
  Phase 2 — bounds ban blast-radius. Signup typically needs a mobile number not
  already bound to an XHS account; VoIP numbers may be rejected. If setup proves a
  fight: fall back to the main account at low volume (see deferred hardening).
- **Auth:** session **cookie + matching User-Agent pair** — `XHS_COOKIE`,
  `XHS_USER_AGENT` in `.env.local`. **Cookies are session credentials = key-grade
  secrets**, guarded in every layer (PreToolUse hook, native deny, `.gitignore`,
  pre-commit grep, CI grep, secretlint value-pattern rules).
- **Expiry:** 2–4 weeks. `XHS_COOKIE_SET_DATE` is written by hand at **every** refresh
  (age is not derivable from the cookie string); `/api/health` warns before expiry.
  The refresh procedure lands in `docs/RUNBOOK.md` at Phase 4.
- **Isolation:** sidecar runs on the **internal compose network only — no published
  host port** (its API is unauthenticated); image pinned to a digest.
- **ToS reality, stated plainly:** automated downloading violates platform ToS. Posture
  is personal use — single user, built-in delays, no redistribution.
- **Provisioning record:** 2026-07-05 — account not created; Phase 2 setup step.

## 5. Bilibili (via yt-dlp)

- **Identity/auth:** **anonymous-first** — no account, no cookie; yt-dlp's 480p
  anonymous cap is fine for LLM extraction. Optional `BILIBILI_COOKIE` (free account,
  `.env.local`) only if on-screen-text OCR ever needs 1080p.
- Same ToS posture as §4: personal use, low volume, delays, no redistribution.
- **Provisioning record:** 2026-07-05 — nothing to provision.

## Deferred hardening (tracked here so it can't fall through the cracks)

| Item | Trigger |
|---|---|
| Switch Gemini to **paid tier** (no training) | Before any personal data (M5/M7) — hard precondition |
| `CHEFCLAW_API_TOKEN` rotation + real TLS | When the stack goes public-internet-facing (M-Deploy; Tailscale-only exposure defers it) |
| Per-user budgets / auth beyond bearer token | Multi-user, if it ever happens (dedicated ADR) |
| Secondary-account fallback note | If throwaway XHS signup fails, main account + low volume is the accepted risk — revisit if throttled/banned |
| DashScope region/data-governance review | Before the fallback adapter's first real call |
