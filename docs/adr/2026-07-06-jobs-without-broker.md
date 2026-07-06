# Jobs without a broker

**Date:** 2026-07-06 · **Context:** Phase 2 — extraction pipeline (branch
`feat/extraction-worker`; records the worker **as shipped**, not as planned)

## Decision

Async extraction runs on the `jobs` table alone — no broker. The worker is
**one in-process asyncio task** started and stopped by the FastAPI app
lifespan, and the api is pinned to **exactly ONE uvicorn worker process**.
Jobs are claimed with a single `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP
LOCKED)` that increments `attempts` **at claim time**, and execute **strictly
serially** — claim one, drive it to a terminal state, repeat. Both constraints
are load-bearing, not tuning knobs: the double-spend race on the paid model
call is closed **only at concurrency 1**.

### Stage machine

`pending → downloading → extracting → validating → stored | failed` (the
claim itself flips `pending → downloading`). The semantics that keep paid
calls safe:

- **Idempotent paid stage:** before any model call the worker re-checks
  `recipes` for the job's `(platform, canonical_id)` and **adopts** existing
  rows instead of extracting — a crash between store and status flip must
  never re-spend.
- **Budget gate before EVERY paid call:** monthly budget + daily attempt cap
  checked immediately before the model call (retries pass through it again by
  construction). `MONTHLY_LLM_BUDGET_USD` / `MAX_EXTRACTION_ATTEMPTS_PER_DAY`
  unset, unparseable, or non-positive ⇒ typed `ConfigError`, **no paid calls
  (fail-closed)**.
- **Ledger per attempt:** one `llm_spend` row per model attempt — **including
  failures and untyped crashes** (a transport error mid-call may have burned
  tokens the adapter couldn't report; fail closed and write the row).
  Zero-token rows still count toward the daily cap, which counts rows, not
  dollars.
- **Retries:** max 3 attempts (counted at claim), **typed-retryable errors
  only**, linear backoff scaled per error type — `rate_limited` waits
  `30s × attempt` (the API said slow down; re-poking it immediately wastes an
  attempt), every other retryable waits `2s × attempt` *(Phase 4 split; was a
  single 2s scale)*. Untyped leaks are terminal — an unknown error must not
  silently burn paid retries.
- **Startup reconcile:** jobs stranded mid-stage by a restart are flipped to
  `failed` / `interrupted` — **explicit human retry only, never auto-rerun
  paid work** (`docker compose watch` restarts the api constantly; auto-rerun
  would turn every restart into a paid call).
- **Atomic store:** the N-recipe insert and the job's flip to `stored` commit
  in **ONE transaction**; an `IntegrityError` from
  `UNIQUE(platform, canonical_id, dish_index)` means a raced duplicate landed
  first — adopt its rows, never error.

### Timeouts, politeness, retention, survival

- **Per-stage deadlines** — download 600 s, extract 900 s — via
  `asyncio.wait_for`; in-code safety bounds, deliberately not config.
- **Politeness delay:** 2–5 s jittered before every platform fetch
  (plan §16.10); skipped for `local` — no platform is touched.
- **Media retention:** `keep` ⇒ fetched media moves to
  `{media_dir}/{platform}/{canonical_id}/` (retention failures are warnings,
  never job failures); `discard` ⇒ deleted. Per-job scratch is ALWAYS cleaned.
- **The worker survives store failures:** the loop is crash-guarded — if the
  store itself raises mid-job (DB outage), the job is left mid-stage for the
  next boot's reconcile and the loop keeps running. A dead worker task means
  no job ever runs again while the api still looks healthy.

## Why

- One user, one video at a time: a broker (Celery/Redis, rejected by name)
  adds an always-on component and its failure modes to serialize work that
  Postgres already serializes with `FOR UPDATE SKIP LOCKED`.
- The cost guardrails compose only at concurrency 1: idempotent paid stage,
  pre-call budget gate, and per-attempt ledger each assume no second claimer
  is mid-extract on the same canonical identity.
- `attempts` counts **claims, not successes**, so a crash loop cannot exceed
  the cap; the ledger row counts **attempts, not dollars**, so the daily cap
  bounds runaway retries even when a failure's token usage is unknown.
- Restart-time auto-rerun was rejected: with paid calls in the pipeline, a
  reconcile that re-queues is a money loop, not a convenience.

## Accepted tradeoffs

- **Cooperative thread cancellation:** the source adapters are async but run
  sync internals (yt-dlp) in `asyncio.to_thread`; cancelling the `wait_for`
  abandons the thread — the download keeps running until yt-dlp returns.
  Compose `init: true` reaps orphaned ffmpeg children; plan §4's process-group
  `killpg` applies when downloads move to subprocess form.
- **Zero-token failure rows (narrowed, Phase 4):** `ExtractionFailedError` /
  `RateLimitedError` now **carry token usage** when the model API surfaced it
  before failing (a billed-but-unparseable response), and the ledger records
  the real tokens. Zeros remain only for failures where usage genuinely never
  existed adapter-side (timeouts, transport errors mid-call) — those rows
  still bound the daily cap while undercounting dollars.
- **No partial unique index on active jobs:** the enqueue dedupe is
  read-then-insert, so a race can create twin pending jobs for one canonical
  identity. The paid call stays single regardless (the idempotent stage adopts
  the first job's recipes); a partial unique index over active statuses is the
  candidate future hardening.
- **Graduation path:** if the workload outgrows strictly-serial (real
  multi-user, multiple workers), the exit is **TaskIQ** — worker logic is
  written against the `JobStore` protocol, so the transport swaps under it.

## Verified (2026-07-06)

- **203 CI-tier tests** (no DB — worker/enqueue/spend logic against the fake
  `JobStore`; `uv run pytest -q`).
- **5 golden DB-tier tests** against a real throwaway Postgres (`-m golden`):
  `FOR UPDATE SKIP LOCKED` claim exclusivity under concurrent claimers;
  atomic store + ledger; unique-violation adopt; hard-delete re-opens
  extraction; **kill-mid-extract ⇒ zero spend** and reconcile flips the job to
  `interrupted`.
