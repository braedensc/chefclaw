# Illustration generation is its own retriable job

**Date:** 2026-07-07 · **Context:** V2-E follow-up, branch `feat/illustration-job-type`
(supersedes the "rejected: a separate `illustration` job type" note in
[Design system & brand](2026-07-06-design-system-and-brand.md))

## Decision

Cover-illustration generation moves out of the extraction worker's best-effort
post-store *stage* and becomes a first-class **`illustration` job type** in the
`jobs` table. After an extraction stores its recipes it enqueues one illustration
job per recipe (`payload = {"recipe_ids": [...]}`, null platform/canonical_id);
the strictly-serial worker dispatches it — skipping download/extract — and runs
the budget-gated, ledgered image generation per recipe. A new running status
`illustrating` is added (terminal states reuse `stored`/`failed`).

The job is **independently retriable and regeneratable on demand**:
`POST /api/recipes/{recipe_id}/illustration` enqueues (or dedupes onto an active)
illustration job. The jobs drawer's Retry for a failed illustration job and a new
"Regenerate illustration" affordance on the recipe detail page both hit that one
endpoint. The startup backfill now **enqueues** illustration jobs for image-less
recipes instead of generating inline — so image generation has exactly one
execution path (the worker's `illustration` branch), and everything flows through
the serial queue.

## Why

- **Retriable + regeneratable was the whole ask.** The inline stage left a
  failed/over-budget image as a silent `image_url = NULL` with no user-facing
  recovery beyond a full re-extraction (which re-pays the model). Promoting it to
  a job gives a failed cover a Retry in the drawer and a one-click Regenerate on
  the detail page, neither of which re-runs extraction. The 2026-07-06 design ADR
  explicitly parked this as the deferred option ("a separate retriable
  `illustration` job type if per-recipe re-generation from the UI is wanted") —
  that trigger fired.
- **One execution path beats two.** Rather than keep the inline post-store stage
  *and* add a job, the post-store enqueue and the startup backfill both now
  enqueue illustration jobs; `_generate_and_persist_illustration` is driven only
  by the worker's `illustration` branch. The backfill dropped its background
  inline generation, so job execution is now *truly* serial (the old backfill
  generated images concurrently with the claim loop — "acceptable concurrency"
  that no longer has to be reasoned about).
- **The load-bearing invariants are unchanged.** Fake-by-default
  (`CHEFCLAW_IMAGE_GENERATOR=fake` — zero spend/network in CI, tests, golden);
  budget + daily-cap gate before **every** paid image call, fail-closed; one
  `llm_spend` row per paid attempt; one uvicorn worker, strictly serial. The
  extraction job now commits recipes and returns *without ever awaiting an image*,
  so the paid-work crash-loss window is closed by construction — a wedged image
  API can only stall a separate illustration job, never the recipe store.
- **Per-recipe jobs, not one batch job** (rejected the batch alternative). A
  1:1 recipe↔illustration↔job mapping makes Retry and Regenerate the *same*
  recipe-scoped endpoint, gives each dish of a multi-dish video an independently
  retriable cover, and sidesteps partial-failure ambiguity. The payload keeps the
  `{recipe_ids: [...]}` shape (single-element today) so a future batch remains
  open. The worker loops over `recipe_ids`, so it is batch-capable regardless.
- **Dedupe gates the paid call, as everywhere else.** `enqueue_illustration`
  returns an already-active illustration job for the recipe instead of stacking a
  twin (`jsonb_exists(payload->'recipe_ids', :id)` over pending/illustrating
  jobs). So a restart re-running the backfill, or an impatient double-click of
  Regenerate, cannot double-spend. A *terminal* job does not dedupe — a genuine
  regenerate of an existing cover always enqueues.
- **Illustration jobs stay out of the canonical-identity dedupe and the golden
  selectors.** Null `platform`/`canonical_id` means they never match
  `find_active_job(platform, canonical_id)`; they carry no `url` and no
  `canonical_id`, so the golden jobs-drawer selector (filters a row by
  `fake-golden-1`) still isolates the extraction job. Chips are unaffected — they
  render only jobs the user pasted this session (`PasteBar onJob`), never the
  worker-enqueued illustration jobs.
- **Reconcile owns a stranded `illustrating` job.** Added to `RUNNING_STATUSES`,
  so a restart flips it to `interrupted` (explicit retry, never auto-rerun) — and
  the startup backfill re-enqueues the still-image-less recipe, so it self-heals.

Accepted tradeoff: a multi-dish video now produces N illustration job rows and N
drawer entries instead of a silent inline pass. That is the point (per-dish
retriability) and is bounded by the same budget guardrails.

## Verified

- **Backend unit tier** (`uv run pytest -q`, no DB): 336 pass. Rewrote the
  illustration suite to drive the job — enqueue-after-store (image deferred,
  `image_url` NULL until drained), per-image ledger attributed to the illustration
  job, generator-error → job `failed`/`illustration_failed`, budget-exceeded → job
  `failed`/`budget_exceeded` (no generate, no spend), config-error, no-live-recipes
  no-op → `stored`, mixed-failure error-type precedence, per-recipe dedupe, and
  reconcile flipping `illustrating` → `interrupted`. `ruff` clean.
- **Golden DB tier** (`-m golden`, throwaway postgres): 10 pass. The full pipeline
  drains illustration jobs against real SQL (real SKIP LOCKED claim →
  `jsonb_exists` dedupe → recipe-slice load → per-row `set_recipe_image`); a
  dedicated test exercises the `jsonb_exists` dedupe + load + terminal-no-dedupe;
  another marks an illustration job `failed` via real SQL. `test_hard_delete_
  reopens_extraction` updated to drain the leftover illustration job.
- **Migration** applied against real postgres (fresh DB, full chain up to head):
  the `ck_jobs_status_enum` CHECK now admits `illustrating`; downgrade→re-upgrade
  roundtrips cleanly (constraint name referenced via `op.f(...)` to match
  migration #1's literal name, not the metadata naming convention).
- **Contract**: `backend/openapi.json` re-exported and `frontend/src/client`
  regenerated (new endpoint + `JobOut.recipe_ids`); the drift generators are
  idempotent (a second run adds nothing).
- **Frontend** (`vitest`): 91 pass incl. new coverage — the drawer Retry for an
  illustration job calls the regenerate endpoint (never re-POSTs extract) and the
  row reads "Cover illustration"; the detail-page control enqueues a cover job and
  labels Generate/Regenerate by `has_image`. Typecheck, ESLint, Prettier clean.
