# Data model & dedupe on canonical identity

**Date:** 2026-07-06 · **Context:** Phase 2 — extraction pipeline (branch
`feat/extraction-worker`; records **migration #1's shape as now exercised** by
the shipped worker — the schema itself landed in Phase 1)

## Decision

Four tables from migration #1 — `users`, `recipes`, `jobs`, `llm_spend` —
with **UUIDv7 primary keys** (Postgres 18 native `uuidv7()`, time-sortable)
and **`owner_id` on every user-owned row from day one** (multi-user insurance
that costs nothing now and is a brutal retrofit later). The load-bearing
shape:

- **`UNIQUE(platform, canonical_id, dish_index)` on `recipes` is THE dedupe
  constraint.** Uniqueness keys on canonical identity — the output of
  `SourceAdapter.resolve()` — **never on raw URLs** (short links, tracking
  params, and Rednote's per-share `xsec_token` make URLs useless as keys; see
  the [source & extractor adapters
  ADR](2026-07-06-source-and-extractor-adapters.md)). The raw pasted URL is
  kept in `recipes.source_url` as provenance only. `dish_index` lets a
  multi-dish video store N sibling rows under one canonical id.
- **`jobs` carries `platform` / `canonical_id` as real queryable columns**
  (the active-job dedupe check filters on them — no JSONB digging), and its
  `payload` stores BOTH `url` (provenance) and `fetch_url` (the resolved
  fetch target): **retries never re-resolve**, which is what preserves a
  Rednote `xsec_token` across attempts.
- **`llm_spend` is written per model attempt, including failures** — the
  ledger is the source of truth for both month-to-date cost and the daily
  attempt cap (`extraction_meta` would undercount exactly when spend runs
  hot; see the [jobs-without-a-broker
  ADR](2026-07-06-jobs-without-broker.md)).
- **`DELETE /api/recipes/{id}` is a hard delete for MVP — and it REOPENS
  extraction:** the completed-job dedupe check returns a stored job only
  while its recipes still exist, so re-pasting a deleted recipe's URL
  enqueues a fresh (paid) job. Golden-tested, not incidental.
- **The recipe `document` JSONB is never user-editable.** `PATCH` accepts
  only `tags` and `user_notes` (`extra="forbid"` rejects everything else);
  the document is written exclusively by the validated pipeline.

## Why

- Dedupe is a **cost control**, not tidiness: the canonical-id check gates
  the paid model call, so the dedupe key must survive URL cosmetics. Only
  resolved identity does.
- Storing `fetch_url` in the job payload trades a little denormalization for
  a hard guarantee — re-resolution on retry would re-hit the platform and,
  for Rednote, could swap a working tokened URL for a dead one.
- A hard delete that re-opens extraction is the honest MVP semantics: with no
  soft-delete state, "deleted" must mean "the system forgets it stored this",
  or a re-paste would dead-end (job says stored, recipes are gone).

## Accepted tradeoffs

- **Partial multi-dish delete quirk:** deleting ONE of a multi-dish video's N
  recipes leaves the sibling rows, so the dedupe check still returns the
  stored job — the deleted dish is not re-extractable without deleting all
  siblings. Deferred to the reserved re-extraction ADR
  (docs/ARCHITECTURE.md), which also owns the stale-`xsec_token` note.

## Verified (2026-07-06)

- **Golden DB tier** (real Postgres, `-m golden`): hard-delete re-opens
  extraction end-to-end (delete → re-paste → fresh job); the atomic
  N-recipe store; unique-violation adopt under a raced duplicate.
- **CI tier** (203 tests, no DB): enqueue dedupe (active job wins, completed
  job with surviving recipes wins, else insert), payload `url`/`fetch_url`
  handling, and the PATCH whitelist (`document` edits rejected).
