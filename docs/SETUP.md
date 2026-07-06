# Setup

Dev-machine setup for **chefclaw**. Honest scope note: the app code (backend/,
frontend/, compose.yaml) lands in **Phase 1** — today the repo is the kit's guardrails
plus docs, and every command in "Works today" actually works.

---

## Prerequisites

| Tool | Version floor | Notes |
|---|---|---|
| macOS or Linux | — | Windows untested |
| git + `gh` | any recent | `gh auth status` must succeed (PRs, CI watching) |
| Python 3 | ≥ 3.9 | Runs the Claude Code hooks; stdlib only, no pip installs |
| Node + npm | ≥ 20 (repo pins **22** via `.nvmrc`) | Kit tooling now; Vite app from Phase 1 |
| Docker Desktop | compose v2 | Needed from Phase 1 (postgres, api, sidecar) |
| uv | latest | **Not yet installed on this machine** — `brew install uv`; needed from Phase 1 (backend/) |

> **Node gotcha:** nvm does **not** apply in non-interactive shells — Claude Code's
> shell and git hooks get the nvm *default* Node, not your terminal's
> (docs/LESSONS.md). `node` currently resolves fine on this machine; if a hook or
> script ever fails on an old Node, run `nvm alias default 22`.

---

## First-time setup (works today)

```bash
gh repo clone <owner>/chefclaw && cd chefclaw
npm install            # installs husky + secretlint; pre-commit hook is now live
npm run test:hooks     # hook battery — green means the guardrails are alive
```

The Claude Code PreToolUse/Stop hooks need no install — they ship in `.claude/` and
are active from the first session.

---

## Environment variables

Copy `.env.example` → `.env.local` **yourself** — Claude is hook-blocked from writing
any `.env*` file by design, so never ask it to. `.env.local` is gitignored and never
committed. Three-stores note: for this self-hosted compose app, `.env.local` is both
the *local* and *host* store; GitHub Actions secrets is the CI store (currently empty
— CI needs no real keys). See docs/SECURITY.md.

| Var | Needed from | Meaning |
|---|---|---|
| `CHEFCLAW_API_TOKEN` | Phase 1 | API bearer token. **Server secret at birth**: never a `VITE_*` var, never in the JS bundle. Entered once in the UI → localStorage. |
| `DATABASE_URL` | Phase 1 | Postgres connection string (local compose DB). |
| `GEMINI_API_KEY` | Phase 2 | Extraction model. Free tier is training-eligible → public cooking videos only; paid tier is a precondition for any personal data. |
| `DASHSCOPE_API_KEY` | Phase 4 | Qwen fallback extractor (config-flagged). |
| `XHS_COOKIE` / `XHS_USER_AGENT` | Phase 2 | Rednote session cookie + the browser UA it was captured with. **Key-grade secret** — a session credential to a real account. |
| `XHS_COOKIE_SET_DATE` | Phase 2 | Set this by hand at **every** cookie refresh — cookie age is not derivable from the cookie string, and `/api/health` uses it to warn *before* the 2–4-week expiry window closes. |
| `BILIBILI_COOKIE` | optional | Anonymous download is the default (480p suffices for extraction); add only if resolution must go up. |
| `MONTHLY_LLM_BUDGET_USD` | Phase 2 | **Fail-closed:** unset or unparseable ⇒ NO paid model calls (typed config error) — not "no cap". Checked before every paid call. |
| `MAX_EXTRACTION_ATTEMPTS_PER_DAY` | Phase 2 | Daily attempt cap (attempts, not videos). Same fail-closed rule. |
| `MEDIA_RETENTION` | Phase 2 | Keep/discard the low-res archive copy of source videos (default: keep). |

---

## Commands

**Works today:**

```bash
npm install                                       # husky + secretlint wiring
npm run test:hooks                                # hook block/allow battery
npm run lint:secrets                              # secretlint over tracked files
python3 scripts/check_placeholders.py --bootstrapped  # no {{…}} tokens remain
```

**Lands in Phase 1** (listed so nobody hunts for them; they do not exist yet):
`docker compose up` (full stack) · `uv sync` / `uv run pytest` / `uv run alembic
upgrade head` (backend/) · `npm run dev` / `npm test` (frontend/) · typed-client
regeneration + CI drift check (@hey-api/openapi-ts).

---

## Testing tiers

| Tier | Runner | Runs where | Needs |
|---|---|---|---|
| Backend unit/API | pytest + httpx `ASGITransport` | CI + local | **Separate test DB** — never the real one |
| Frontend unit/component | Vitest 4 + Testing Library | CI + local | Nothing — mocked |
| E2E smoke | Playwright | CI (**non-required**) | Nothing — dummy env, **no database**; proves boots-and-renders only |
| Golden paste-to-card | Playwright vs local compose stack | **LOCAL ONLY** | Separate test DB/compose project + config-selected **fake** Source/Extractor adapters |

The golden suite fakes adapters via server config, not browser route-mocking — Gemini
is called server-side in the worker, where the browser can't intercept it.

> **Kit inversion (read this):** the kit default assumes the local DB is disposable.
> In chefclaw the local Docker DB holds **irreplaceable production data** (your recipe
> library). All test suites run against a *separate* test database/compose project,
> never the real one — and the PreToolUse hook blocks volume-destroying commands
> (`down -v`, `volume rm`, `volume prune`, `system prune --volumes`, `compose rm -v`)
> for both irreplaceable volumes (DB + media archive).

---

## Local services (compose — lands in Phase 1/2)

| Service | Address | Phase | Notes |
|---|---|---|---|
| postgres | 127.0.0.1:5432 | 1 | Postgres 18; **named volume, irreplaceable data** (see kit inversion) |
| api | 127.0.0.1:8000 | 1 | FastAPI, **exactly one uvicorn worker** (hard constraint of the no-broker job design); serves the SPA same-origin in prod-mode; media archive on a named volume |
| web | 127.0.0.1:5173 | 1 | Vite dev server, proxies `/api` to the api |
| xhs sidecar | **internal network only — no host port** | 2 | Its API is unauthenticated, so it is never published to the host; image pinned to a digest |

All published ports bind to `127.0.0.1` — nothing listens on the LAN.

---

## Troubleshooting

- **A hook blocked my edit/commit** — the system working, not a bug. Branch first
  (`git checkout -b <type>/<short-kebab-desc>`) and retry; never work around a block.
- **Every tool call is blocked** — the hooks fail closed. Two causes: `python3`
  missing from PATH (install it), or a syntax-broken hook script. The hooks are
  self-protected, so Claude cannot repair them — a **human** fixes the file via
  terminal (docs/SECURITY.md runbook).
- **Old Node in hooks or scripts** — the nvm non-interactive gotcha above:
  `nvm alias default 22`, or export the absolute Node path (docs/LESSONS.md).
- **`uv: command not found`** — it isn't installed yet; `brew install uv`
  (needed from Phase 1, not before).
