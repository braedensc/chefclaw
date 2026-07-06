# Setup

Dev-machine setup for **chefclaw**. Every command below works today — the Phase 1
walking skeleton (backend/, frontend/, compose.yaml) has landed.

---

## Prerequisites

| Tool | Version floor | Notes |
|---|---|---|
| macOS or Linux | — | Windows untested |
| git + `gh` | any recent | `gh auth status` must succeed (PRs, CI watching) |
| Python 3 | ≥ 3.9 | Runs the Claude Code hooks; stdlib only, no pip installs |
| Node + npm | ≥ 20 (repo pins **22** via `.nvmrc`) | Kit tooling now; Vite app from Phase 1 |
| Docker Desktop | compose v2 | postgres + api stack (sidecar from Phase 2) |
| uv | ≥ 0.11 | `brew install uv` — the backend/ toolchain |

> **Node gotcha:** nvm does **not** apply in non-interactive shells — Claude Code's
> shell and git hooks get the nvm *default* Node, not your terminal's
> (docs/LESSONS.md). `node` currently resolves fine on this machine; if a hook or
> script ever fails on an old Node, run `nvm alias default 22`.

---

## First-time setup (works today)

```bash
gh repo clone <owner>/chefclaw && cd chefclaw
npm install            # installs husky + secretlint + frontend workspace deps
npm run test:hooks     # hook battery — green means the guardrails are alive
git config core.hooksPath   # MUST print .husky/_ — if empty, run: npm run prepare
cd backend && uv sync && cd ..   # backend venv
```

> **Verify the pre-commit layer actually wired** (the `git config` line above): on
> one machine `npm install`'s husky `prepare` silently failed to set
> `core.hooksPath`, which disables the local secret scan without any error. If it
> prints nothing, `npm run prepare` fixes it. (Bootstrap PR #1 notes.)

The Claude Code PreToolUse/Stop hooks need no install — they ship in `.claude/` and
are active from the first session.

**Run the full stack** (prod-mode: the api serves the built SPA same-origin):

```bash
CHEFCLAW_API_TOKEN=pick-something docker compose up -d --build
open http://127.0.0.1:8000        # paste the same token into the token gate
# once .env.local exists, prefer: docker compose --env-file .env.local up -d
```

**Dev loop** (hot reload): `docker compose up -d postgres migrate` for the DB, then
`uv run python -m chefclaw.main` in backend/ and `npm run dev` at the root (Vite on
127.0.0.1:5173, proxying `/api` to the api).

---

## Environment variables

Copy `.env.example` → `.env.local` **yourself** — Claude is hook-blocked from writing
any `.env*` file by design, so never ask it to. `.env.local` is gitignored and never
committed. Three-stores note: for this self-hosted compose app, `.env.local` is both
the *local* and *host* store; GitHub Actions secrets is the CI store (currently empty
— CI needs no real keys). See docs/SECURITY.md.

| Var | Needed from | Meaning |
|---|---|---|
| `CHEFCLAW_API_TOKEN` | Phase 1 | API bearer token. **Server secret at birth**: never a `VITE_*` var, never in the JS bundle. Entered once in the UI → localStorage. Empty ⇒ the api 401s every request with instructions (disabled-closed). |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | Phase 1 | Postgres connection **parts** — the app assembles the URL so no URL-with-password string ever exists in a file. Defaults match the local compose stack. |
| `GEMINI_API_KEY` | Phase 2 | Extraction model. Free tier is training-eligible → public cooking videos only; paid tier is a precondition for any personal data. |
| `DASHSCOPE_API_KEY` | Phase 4 | Qwen fallback extractor (config-flagged). |
| `XHS_COOKIE` / `XHS_USER_AGENT` | Phase 2 | Rednote session cookie + the browser UA it was captured with. **Key-grade secret** — a session credential to a real account. |
| `XHS_COOKIE_SET_DATE` | Phase 2 | Set this by hand at **every** cookie refresh — cookie age is not derivable from the cookie string, and `/api/health` uses it to warn *before* the 2–4-week expiry window closes. |
| `BILIBILI_COOKIE` | optional | Anonymous download is the default (480p suffices for extraction); add only if resolution must go up. |
| `MONTHLY_LLM_BUDGET_USD` | Phase 2 | **Fail-closed:** unset or unparseable ⇒ NO paid model calls (typed config error) — not "no cap". Checked before every paid call. |
| `MAX_EXTRACTION_ATTEMPTS_PER_DAY` | Phase 2 | Daily attempt cap (attempts, not videos). Same fail-closed rule. |
| `MEDIA_RETENTION` | Phase 2 | Keep/discard the low-res archive copy of source videos (default: keep). |
| `CHEFCLAW_BACKUP_DIR` | Phase 4 | Where `scripts/backup.sh` writes encrypted artifacts — point it at `<your-backup-destination>` (ideally synced/off-machine). |
| `BACKUP_GPG_PASSPHRASE` | Phase 4 | Symmetric backup key. Generated once, **password manager first** (canonical copy) — `.env.local` holds only the operational copy; never only on this machine. |
| `CHEFCLAW_BACKUP_INCLUDE_MEDIA` | optional | `0` skips the media-volume archive (default `1`; the script warns past 1 GiB). |

---

## Commands

```bash
# Stack
docker compose up -d --build              # postgres + migrate + api (SPA at :8000)
docker compose down                       # containers only — volumes ALWAYS survive

# Backend (in backend/)
uv run pytest -q                          # unit tier — no DB needed
uv run ruff check .
uv run alembic upgrade head               # against the compose DB (parts env)
uv run python -m chefclaw.export_openapi openapi.json   # regen schema (drift-checked)

# Frontend / workspace root
npm run dev                               # Vite dev server, /api proxied to :8000
npm test · npm run lint · npm run format:check · npm run typecheck
npm run test:e2e                          # Playwright smoke (no DB, dummy env)
npm run generate:client -w frontend       # regen typed client (drift-checked)

# Golden suite (LOCAL ONLY): its own compose stack — tmpfs DB, fake adapters,
# project chefclaw-golden on 127.0.0.1:8100/55433 — never the real one.
docker compose -f compose.golden.yaml up -d --build
npm run test:golden
docker compose -f compose.golden.yaml down   # plain down — it has no volumes

# Backups (procedures + performed drill record: docs/RUNBOOK.md §2)
sh scripts/backup.sh                      # encrypted pg_dump + media archive — read-only vs the stack
# schedule daily via launchd: ops/com.chefclaw.backup.plist.example (install steps in its header)

# Kit guardrails
npm run test:hooks                        # hook block/allow battery
npm run lint:secrets                      # secretlint over tracked files
python3 scripts/check_placeholders.py --bootstrapped
```

**Regenerating the API contract:** any backend route/schema change ⇒ re-export
`openapi.json`, regenerate the client, commit both — the "OpenAPI drift" CI job
fails otherwise.

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

## Local services

| Service | Address | Status | Notes |
|---|---|---|---|
| postgres | 127.0.0.1:5432 | live | Postgres 18; volume `chefclaw_pgdata` — **irreplaceable data** (see kit inversion) |
| migrate | one-shot | live | `alembic upgrade head`, exits; the api waits for it |
| api | 127.0.0.1:8000 | live | FastAPI, **exactly one uvicorn worker** (no-broker constraint); serves the built SPA same-origin; volume `chefclaw_media` reserved for the Phase-2 archive |
| Vite dev server | 127.0.0.1:5173 | host-run (`npm run dev`) | proxies `/api` to the api — same-origin holds in dev |
| xhs sidecar | **internal network only — no host port** | Phase 2 | Its API is unauthenticated, so it is never published to the host; image pinned to a digest |

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
- **`uv: command not found`** — `brew install uv`.
- **api answers 401 to everything** — `CHEFCLAW_API_TOKEN` is unset in the api's
  environment (disabled-closed by design). Set it inline or via
  `docker compose --env-file .env.local up`.
