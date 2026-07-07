# In-app admin config panel: runtime-policy overrides via an `app_config` table

**Date:** 2026-07-07 · **Context:** branch `feat/admin-config-panel` — the owner-facing
admin console gains a **Config** section so operational *policy* can change without editing
`.env.local` and restarting the box. Follow-up to the admin-console consolidation goal
(one in-app panel for settings + user management). Builds on
[M2 accounts + invites](2026-07-07-m2-accounts-and-invites.md) (`require_admin`),
[M3 per-user caps](2026-07-07-per-user-budget-caps.md) (the budget gate + `/api/health`
effective-cap readout), and [the cover system](2026-07-07-cover-system-sprites-and-private-frames.md)
(the cover-mode knobs).

## Decision

Introduce a tiny **`app_config`** key/value table whose rows **override the environment
`Settings` at read time**, for a **closed allowlist of exactly eight runtime-policy flags**
— never secrets, never infra. One code-side **registry** (`chefclaw/app_config.py`) is the
source of truth for which keys are editable, their type/coercion, and their write-validation;
the table is dumb text. One accessor, `effective_settings(base, sessionmaker) ->
base.model_copy(update=<coerced overrides>)`, reuses the existing
`extractor_settings_for_tier` copy idiom and is injected at exactly two edges: an async
FastAPI dependency (`/api/health`, the config API) and **once per job in the strictly-serial
worker**. Changes therefore land on the **next job — no restart** for these eight; infra and
secrets stay env-only with a documented restart boundary and are surfaced read-only. A
`PATCH /api/admin/config` behind `require_admin` writes overrides, records every change in an
append-only **`config_audit`** table (+ a structured log line), and **cannot** touch a secret
or an unknown key. Fail-closed is preserved end-to-end.

The eight editable flags (three buckets):

| Bucket | Keys |
|---|---|
| Covers | `chefclaw_image_generator` (sprite\|fake\|gemini), `chefclaw_real_covers` (bool) |
| Model tier | `gemini_model`, `gemini_paid_model` (free-text ids), `gemini_media_resolution` (low\|medium\|high), `gemini_media_resolution_max` (""=off, or a resolution strictly above the base) |
| Budget | `monthly_llm_budget_usd`, `max_extraction_attempts_per_day` (both raw strings, parsed fail-closed downstream) |

Everything else in `config.py` stays env-only: **secrets** (`gemini_api_key`,
`google_oauth_client_secret`, `xhs_cookie`/`xhs_user_agent`, `bilibili_cookie`,
`dashscope_api_key`, `db_password`, `chefclaw_api_token`) are shown as **status only**
(`configured` / `not`), never a value; **deploy/infra** (auth provider, OAuth client id/redirect,
email/SES, `public_base_url`, DB coordinates, sources, sidecar URL, fetch proxy, media/scratch
dirs, Sentry env/release, log format/level, backup state file, session TTL/idle, rate limits)
are shown **read-only** with a "restart required" note.

## Why

**Forces.** Today, flipping the cover mode, the global model tier, resolution escalation, or
the global budget means editing `.env.local` on the host and restarting the one uvicorn
process — friction the owner hits often (tuning spend, A/B-ing sprite vs. gemini covers,
turning escalation on for a QA run). But three Hard Rules (2/3/4) forbid a secret ever landing
in a DB value or a client bundle, and several env vars (auth provider, DB coordinates) are
load-bearing at boot and *should* require a deliberate restart. So the answer is a **narrow**
override surface, not a general "edit any setting" panel.

**Row-present = override; row-absent = inherit env** — a deliberate three-state model, because
"disable" and "inherit" differ and money depends on the difference:

- no row → use the env value;
- row with `value = "X"` → use `X`;
- row with `value = ""` → **explicit empty, shadows env** (for budget = *disable paid calls*;
  for `gemini_media_resolution_max` = *escalation off*).

`PATCH {key: "..."}` upserts; `PATCH {key: null}` **deletes** the row (revert to env) — the same
partial-update / `null`-clears semantics M3's per-user budget PATCH already established, so the
mental model is consistent across the admin surface.

**One accessor, `model_copy(update=...)`.** The codebase already threads a `Settings` value
object everywhere and already builds effective copies this way
(`extractor_settings_for_tier(settings, …)` at `extractors/__init__.py:129`). Overlaying the
eight keys onto a copy means **zero change at the ~10 read sites** — they keep reading
`settings.gemini_media_resolution` etc., they just receive the effective object. The registry
coerces stored text to the field's Python type before the copy (only `chefclaw_real_covers` is
non-str), matching "the inferred type IS the type".

**Worker pickup = per job, no restart.** The worker is a single strictly-serial asyncio task
(a hard invariant of the no-broker design). It resolves `effective_settings(...)` once at the
top of each job — a single indexed read of a ≤8-row table — and threads that copy through the
extractor tier, image generator, real-frame gate, and the budget check. A policy change is thus
picked up on the **next** job; an in-flight job keeps the config it started with (no mid-job
mutation). This is the whole reason these eight were chosen: each is read *fresh per job*, so it
is safe to re-read per job. Infra/secrets are read at boot into long-lived objects (the OAuth
provider, the DB engine) — re-reading them per request would be wrong, so they keep the restart
boundary, and the panel says so per field.

**Fail-closed holds (Hard Rule / §16.8).** The overlay only ever *supplies* the eight keys; it
can never remove the fail-closed gate. Clearing the budget override (or setting it to `""`)
yields an empty string → `spend.parse_budget` raises `ConfigError` → **no paid calls**, exactly
as an unset env var does today. Write-validation therefore *allows* `""` for the two budget keys
(that is the "disable" action) but rejects non-numeric / non-positive input, so the panel gives
immediate feedback without ever letting the runtime silently mis-behave. **Defense in depth:** the
`gemini_media_resolution_max > base` cross-field rule is validated on write by constructing the
*candidate* effective `Settings` and running the same check the `GeminiExtractor` constructor
runs — and even if a bad combo ever reached the table, the constructor *still* raises
`ConfigError` per job, so the job fails **surfaced and safe**, never crashes the worker or
fabricates output.

**Secrets never enter the table.** The registry contains only the eight non-secret keys;
`PATCH` 422s any key outside it, and the loader ignores rows whose key isn't registered (a
removed key's stale row is inert). Secret *status* is derived as a boolean from the env
`Settings` (`bool(settings.gemini_api_key)`) and shown read-only — the value is never read into
a response, a log, or the table. Because only non-secret keys are reachable, the `config_audit`
`old_value`/`new_value` are never secret either.

**Audit = append-only table + log.** Global policy that moves money deserves durable, queryable
history, not just a log line that rotates away. `config_audit` (key, old→new, `changed_by` FK to
`users`, `created_at`) mirrors the kit's append-only idiom (`llm_spend`, `request_events`,
`cover_misses`); a structured log line is *also* emitted for real-time observability. Like
`invites`, `app_config` itself carries **no `owner_id`** — it's a system artifact, not a
user-owned row; `config_audit.changed_by` records *which admin* for provenance only.

**Alternatives rejected.**
- *Hot-reload the whole `Settings` from a DB source (a second `pydantic-settings` layer).*
  Rejected: it would blur the secret/infra boundary and make an accidental mid-flight auth-provider
  or DB-host flip possible. A narrow eight-key overlay keeps the blast radius auditable.
- *Typed-per-column or JSON `app_config`.* Rejected: text + a code-side registry keeps the type
  as one source (the `Settings` field) and avoids a wide, migration-coupled table.
- *A DB `CHECK (key IN (...))`.* Rejected: it couples "add a runtime flag" to a migration; the
  registry is code-side and the loader is defensively lenient to unknown rows.
- *Write to `.env` / mutate `os.environ`.* Rejected outright — Claude never writes `.env*`
  (hook-blocked), it needs a restart, it isn't atomic, and it isn't auditable.
- *Audit via logs only.* Rejected for money-affecting policy (durable history wins); logs are
  still emitted.
- *A settings cache with invalidation.* Rejected as premature — a ≤8-row table on non-hot paths.
  **Deferral trigger:** if profiling shows a hot path re-reading the overlay (e.g. the card-grid
  `/image` real-covers check under load), add a short-TTL process cache then, in its own change.

## Phasing

1. **Data + accessor** — one migration off head `a1c2e3f4b5d6` creating `app_config` +
   `config_audit`; `models.py` rows; `app_config.py` (registry, coercion, write-validation,
   `load_overrides`, `effective_settings`); wire the accessor into the worker (per job), the
   store's `check_budget`, and `/api/health`. Unit tests.
2. **Admin API** — `GET`/`PATCH /api/admin/config` behind `require_admin` (three GET sections:
   editable runtime-policy + secret status + read-only infra; PATCH = runtime-policy keys only,
   partial, `null`-clears, cross-field-validated, audited). Re-export `openapi.json`.
3. **Frontend** — regenerate the typed client; add an `/admin/config` route + `admin-config-page.tsx`
   + admin nav link, styled in the existing neon system; Vitest.
4. **Verify** — unit + golden (a config PATCH visibly changes worker behaviour) + Vitest all green,
   OpenAPI-drift clean, then PR.

One branch, one PR, phased into reviewable commits (the migration chains off the *latest* head —
re-checked for duplicate revision ids immediately before generating, per the parallel-session note).

## Verified

*Acceptance matrix the implementation PR must turn green (this ADR is written first; results are
amended in below once the tests run).*

- **Overlay precedence** — with `MONTHLY_LLM_BUDGET_USD=10` in env and an `app_config` row
  `monthly_llm_budget_usd="25"`, `effective_settings(...)` reports `25`; deleting the row reverts
  to `10`; a row `""` makes `parse_budget` raise `ConfigError` (no paid calls). Same three-state
  proven for `gemini_media_resolution_max` (off / on / cleared).
- **Worker picks up without restart** — golden: extract once in `sprite` mode → sprite cover;
  `PATCH {chefclaw_image_generator: "fake"}`; extract again in the *same* process → the fake
  image path runs. No process bounce between the two.
- **Fail-closed** — clearing the budget override (env also empty) ⇒ the extract job fails with the
  typed budget `ConfigError`, zero `llm_spend` rows written. A `gemini_media_resolution_max` not
  above base is 422'd on write **and**, if force-inserted, fails the job surfaced (worker survives).
- **Secret containment** — `PATCH {gemini_api_key: "x"}` → 422 unknown key; no secret value appears
  in any `GET /api/admin/config` body, in `config_audit`, or in logs (asserted). Secret *status*
  flips `false`→`true` purely from env presence.
- **AuthZ** — `GET`/`PATCH /api/admin/config` as a non-admin owner → 403 (`require_admin`),
  unauthenticated → 401.
- **Audit** — every successful PATCH writes exactly one `config_audit` row with the correct
  old→new and `changed_by`; a no-op / rejected PATCH writes none.
- **Contract** — `openapi.json` + generated client regenerated and committed (drift CI green);
  Vitest covers the panel's load / edit / clear / validation-error paths.
