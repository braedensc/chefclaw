# Data model

The contract future pillars read. Kept current with every migration — a schema
change that doesn't update this file in the same PR is incomplete. Source of
truth: `backend/alembic/` migrations; design rationale:
`planning/chefclaw-plan.md` §5 + §16 (gitignored) and `docs/adr/`.

**Migration #1** (Phase 1 walking skeleton) creates all four tables. `owner_id`
lands on every user-owned row from day one — multi-user insurance that costs
nothing now and is a brutal retrofit later. All primary keys are UUIDv7 via
Postgres 18's native `uuidv7()` (`server_default`), so ids are time-sortable and
stable — future agents and clients reference them.

## users

One seeded owner row (single-user MVP). Per-user budgets/auth/preferences arrive
only if real users do.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | `uuidv7()` |
| `name` | text | seeded `'owner'` |
| `created_at` | timestamptz | server default |

## recipes

Normalized spine + JSONB document.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | `uuidv7()` |
| `owner_id` | uuid fk → users | indexed |
| `title_en` / `title_original` | text | original language is data — never dropped |
| `platform` | text | `bilibili` \| `rednote` |
| `source_url` | text | the raw pasted URL — **provenance only**, never a dedupe key |
| `canonical_id` | text | platform-native id (BV id + part, note id) resolved by the `SourceAdapter` |
| `dish_index` | int, default 0 | a multi-dish video yields N rows sharing a canonical id |
| `status` | text | enumerated: `extracting` \| `stored` \| `failed` |
| `tags` | text[] | user-editable (PATCH) |
| `user_notes` | text | user-editable (PATCH) |
| `document` | jsonb | the Pydantic-validated recipe document — **never user-editable** |
| `extraction_meta` | jsonb | model id, prompt version, warnings, media resolution, timestamps |
| `created_at` | timestamptz | |

**`UNIQUE(platform, canonical_id, dish_index)`** — the dedupe constraint. Raw
URLs cannot dedupe (b23.tv short links + tracking params; Rednote per-share
`xsec_token`), so uniqueness keys on canonical identity. The canonical-id check
gates the paid model call, after resolution. `DELETE` is a **hard delete** for
MVP **and re-opens extraction** — the dedupe check returns a completed job only
while its recipes still exist, so re-pasting a deleted recipe's URL enqueues a
fresh (paid) job (golden-tested; see
adr/2026-07-06-data-model-and-dedupe.md). Re-extraction semantics are a named
future ADR (see docs/ARCHITECTURE.md).

Reserved (dormant until later pillars): `times_cooked`, per-ingredient
`nutrition_ref` inside `document`. A meal-log/plan-history table arrives with M6
— deliberately not created now.

## jobs

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | `uuidv7()` |
| `owner_id` | uuid fk → users | |
| `type` | text | `extract` \| `upload` |
| `payload` | jsonb | stores both `url` (provenance) and `fetch_url` (resolved) — retries never re-resolve, preserving a Rednote `xsec_token` |
| `platform` / `canonical_id` | text | real columns (queryable) for the active-job dedupe check |
| `status` | text | `pending` \| `downloading` \| `extracting` \| `validating` \| `stored` \| `failed` |
| `attempts` | int, default 0 | max 3, then terminal `failed` |
| `error_type` / `error_detail` | text | the typed error taxonomy (plan §4 + config-error amendment) |
| `result_recipe_ids` | uuid[] | multi-dish results |
| `created_at` / `updated_at` | timestamptz | claim index on `(status, created_at)` |

Worker semantics (shipped — full record in
adr/2026-07-06-jobs-without-broker.md): claimed via
`FOR UPDATE SKIP LOCKED` with `attempts` incremented at claim; **strictly
serial execution**; the N-recipe insert and the job's flip to `stored` happen
in **one transaction**; startup reconcile marks orphaned running jobs
`failed`/`interrupted` — never auto-re-run paid work.

## llm_spend

The cost ledger — written **per model attempt, including failures** (that's when
spend runs hot and `extraction_meta` would undercount). A failed attempt whose
error carried no token accounting is recorded with **zero tokens** — the row
still counts toward the daily attempt cap (which counts rows, not dollars);
dollar undercounting on failures is a known limitation until typed errors
carry usage.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | `uuidv7()` |
| `job_id` | uuid fk → jobs | |
| `owner_id` | uuid fk → users | indexed with `created_at` (month-to-date query) |
| `model` | text | model id is config, never hardcoded |
| `tokens_in` / `tokens_out` / `tokens_thinking` | int | |
| `cost_usd` | numeric(10,6) | bias arithmetic conservative — the kill-switch trips early, never late |
| `created_at` | timestamptz | |

Budget guardrails fail closed: `MONTHLY_LLM_BUDGET_USD` /
`MAX_EXTRACTION_ATTEMPTS_PER_DAY` unset or unparseable ⇒ no paid calls (typed
config error). Budget + daily-cap check runs before **every** paid call.
