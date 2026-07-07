# Owner-editable estimates & the derived-vs-user merge posture

**Date:** 2026-07-07 · **Context:** follow-up to the V2-E design PR (#16) — resolves the
open question flagged in [Design system & brand](2026-07-06-design-system-and-brand.md)
("an owner-editable classification for the two estimates")

## Decision

The two derived 0–3 estimates (`estimated_spiciness_level`,
`estimated_difficulty_level`) become **owner-editable** via `RecipePatch`, joining
`tags` / `user_notes` on the PATCH whitelist (`extra="forbid"` still rejects everything
else — the raw `document` remains never-editable). Any correction rebuilds the whole
`estimated` column flagged **`source="user"`**; extraction output stays **`source="derived"`**
and the model can never claim `"user"` (`validate_estimated` strips any model-supplied
`source`, exactly as document provenance is pipeline-owned). A `"user"` object takes
precedence over the model's derivation and **must survive any future re-derivation** — the
deferred re-extraction ADR inherits this as a hard constraint, not a preference. The API
projects a read-only `estimated_source` so the UI drops the "(estimated)" affordance once
an owner has overridden.

## Why

- **One `source` for the pair, not per-field provenance.** The `estimated` object carries a
  single `source`, so *any* edit makes the whole object owner-authored (an untouched level
  rides along). Coarse but honest: it is the simplest signal a re-derivation can respect,
  and it matches the existing one-`source` schema. *Rejected:* per-field provenance (a
  nested or doubled `source`) — a real schema change for fidelity no MVP surface needs; a
  noted future refinement.
- **Clearing is an owner decision, not a reset.** Setting a level to `null` keeps the
  object (`{…, source:"user"}`), never collapsing to a null column. A null column reads as
  "no estimate yet" and a re-derivation would re-fill it; keeping the `"user"` flag says
  "the owner curated this to empty — hands off." *Rejected:* collapse-to-null (loses owner
  intent against the very re-derivation this flag exists to gate).
- **Provenance stays pipeline-owned.** `EstimatedAttributes.source` widened to
  `Literal["derived","user"]`, but `validate_estimated` drops any model-supplied `source`
  before validating, so an extraction is *always* `"derived"`. *Rejected:* widening the
  literal without stripping — a buggy/hostile model could then mark its own guess
  `"user"`, the estimate equivalent of the source-block spoof the document schema already
  forbids.
- **Values validated at the boundary, no silent coercion.** The two PATCH fields are
  `int | None`, `ge=0, le=3, strict=True` — out-of-range, `True` (bool→int), and `1.5`
  (float→int) are all 422s, mirroring the document schema's coercion contract. Merge
  re-validates through `EstimatedAttributes` so the stored shape can only ever be the
  schema's.
- **Hard Rule 7 intact.** These were always assessments in a *separate flagged column*,
  never verbatim food data in the `document`. Making the flagged column owner-editable does
  not touch a single verbatim capture; the `document` JSONB is as immutable as before.
- **Affordance follows provenance across reloads.** The UI needs to know "estimate vs
  owner value" durably, so the server exposes `estimated_source` (not a client-only
  optimistic flag that a refetch would forget). The scale components gain an `estimated`
  prop (drop the "(estimated)" label) and a `decorative` prop (a live, unlabelled preview
  beside the `<select>` that is the real control — so the editor preview never
  double-registers the hero scale's accessible label). *Rejected:* local-only override
  state (wrong after reload); an `aria-hidden` wrapper (`getByLabelText` ignores it, so the
  duplicate label would still collide).

## Verified

- **Backend, CI tier (no DB):** `uv run pytest -q` green (339). New: `_merge_user_estimate`
  unit matrix (overlay, null-column start, clear-one, clear-both-still-`user`, re-edit of a
  `user` object); PATCH forwards both levels incl. explicit `null`; 422 on out-of-range /
  bool / float and on a stray `estimated` body key (service never called); projection now
  carries `estimated_source` and survives response revalidation. `ruff check` clean.
- **Backend, golden DB tier (throwaway Postgres, `-m golden`):** the full
  `patch_recipe` round-trip flips a `derived` 1/1 to `user` 3/1 through real JSONB column
  reassignment, the untouched level rides along, and a stranger `owner_id` gets `None`
  (owner-scoping holds). 9 golden tests pass.
- **Contract:** `openapi.json` re-exported and `frontend/src/client` regenerated in this PR
  (the two `RecipePatch` fields + the `estimated_source` union) — the drift job is
  satisfied.
- **Frontend:** typecheck / eslint / prettier clean; Vitest green (93) — scale `estimated`
  toggle, the ratings edit flow (both levels sent as one override), clear-sends-`null`, and
  the hero dropping "(estimated)" when `estimated_source==="user"`. Playwright smoke green
  (token-gate contract untouched).
