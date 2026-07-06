# V2-A: Observability & cost management

**Date:** 2026-07-06 · **Context:** v2 milestone V2-A (branch `feat/observability-and-cost`) — first PR after the MVP merge (#1–#10); prerequisite for the VPS deploy (V2-B): never debug a remote box with no logs, no error tracking, and no spend visibility.

## Decision

Three observability layers, all opt-in by env presence and zero-cost when absent:

1. **Sentry, DSN-gated** (the kit pattern, `docs/STACK-RATIONALE.md`): backend
   (`sentry-sdk[fastapi]`) and frontend (`@sentry/react`) initialise **only when
   `SENTRY_DSN` / `VITE_SENTRY_DSN` is present** — no DSN ⇒ no-op, so dev, CI, and
   tests send zero events by construction. Tagged `environment` (`SENTRY_ENVIRONMENT`,
   default `local`) and `release` (git SHA baked at image build via the `GIT_SHA`
   build arg). The **worker is the priority client**: a job failing terminally
   captures an event tagged `job_id` + `stage` + `error_type` + `platform` + attempt;
   retryable requeues leave breadcrumbs, not issues. Tracing/replay stay off
   (`traces_sample_rate=0`) — error tracking only, free-tier friendly.
2. **Structured JSON logs** on stdlib `logging` (no new dependency): a JSON formatter
   on stdout (journald/`docker compose logs`-friendly), `CHEFCLAW_LOG_FORMAT=json|text`
   (default `json`), level via `CHEFCLAW_LOG_LEVEL`. A pure-ASGI request-log middleware
   records method, path, status, duration, and the resolved `owner_id` for `/api/*`
   only (`/api/health` at DEBUG — it is polled every 15 s). Job lifecycle events
   (claim → stage transitions → terminal, with per-stage timings) carry structured
   `job_id`/`stage`/`error_type` fields. Hard rule preserved: **no secret values, no
   raw sidecar bodies** in any log line; Sentry gets an explicit event-scrubber
   denylist for our secret names on top of its defaults.
3. **Spend surfacing (extend the existing ledger, don't rebuild):**
   `GET /api/spend?days=` returns a per-day, per-model breakdown (cost, attempts,
   tokens) plus month-to-date and the configured caps; `/api/health` now reports
   `budget_monthly_usd` + `daily_attempt_cap` (both `null` when fail-closed),
   `attempts_today`, worker aliveness, and whether Sentry is on — so the Settings
   screen renders the **real** budget instead of the mirrored frontend constant
   (known Phase-4 follow-up, now closed). Crossing **80% / 100%** of
   `MONTHLY_LLM_BUDGET_USD` emits a structured warning log + a Sentry message —
   crossing-edge detection (before < threshold ≤ after), so one alert per threshold
   per month, not one per attempt.

## Why

- **Sequencing:** V2-B puts this stack on a VPS. Logs+errors+spend must exist first
  (v2 plan §0) — this is the cheap milestone that unblocks everything after it.
- **DSN-gating over config flags:** presence-of-env is unforgeable by defaults and
  needs no test-mode plumbing — CI/tests literally cannot send events. Rejected:
  self-hosted Sentry/GlitchTip (an ops burden the size of the app itself) and
  log-only error tracking (no aggregation, no alerting, invisible from the phone).
- **stdlib JSON over structlog:** one small formatter we own versus a new dependency
  and its config surface; journald and `docker compose logs` want plain stdout lines
  either way. Rejected: uvicorn access logs as the request log (no latency, no owner
  scope, no JSON) — they are silenced in favor of the middleware.
- **Worker aliveness = task-not-done, not heartbeat timestamps:** the real failure
  mode is the asyncio task dying while the API keeps answering (documented risk in
  `services/jobs.py`); a timestamp heartbeat false-alarms during any long legitimate
  download/extract stage (up to 15 min), so it was rejected.
- **Crossing-edge budget alerts** (not level checks) keep the ledger write path
  idempotent-noisy-free: an alert fires the attempt that crosses a threshold, and
  alerting failures never break `record_spend` (alerting is wrapped, best-effort).
- **DSN posture:** a DSN is an ingest address, not a credential (STACK-RATIONALE);
  it may appear in the client bundle (`VITE_SENTRY_DSN`) without violating Hard
  Rule 4, which governs server keys. It still lives in `.env.local` per the
  three-stores model.

## Verified

- `uv run pytest -q` unit tier: DSN-absent ⇒ `init_sentry` returns False and the
  SDK stays un-initialised (proven by assertion, not convention); with a dummy DSN +
  capturing transport, a job failing terminally produces exactly one event tagged
  `job_id`/`stage`/`error_type`; threshold-crossing math covered at 80/100 edges
  (including budget-shrink and multi-threshold-in-one-attempt cases); `/api/spend`
  shape + auth (401 without token) covered with a fake reader; health reports caps
  `null` under fail-closed config.
- Request middleware asserted via `caplog`: one INFO line per `/api/*` request with
  method/path/status/duration/owner, `/api/health` demoted to DEBUG.
- Golden DB tier (`-m golden`, throwaway PG): the per-day/per-model SQL aggregation
  returns correct buckets across UTC day boundaries.
- Fail-closed re-verified end-to-end: budget vars unset ⇒ `check_budget` raises
  `ConfigError`, `/api/health` shows `budget_monthly_usd: null`, Settings renders
  the fail-closed warning.
