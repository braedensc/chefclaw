# Cover system: curated sprites (default) + private real-frame covers

**Date:** 2026-07-07 · **Context:** V2-F (v2 plan §V2-F), branch
`feat/cover-system-sprites-and-private-frames` (supersedes the generated-Gemini-
illustration cover from [Design system & brand](2026-07-06-design-system-and-brand.md)
and [Illustration generation is its own retriable job](2026-07-07-illustration-job-type.md)
as the DEFAULT cover source — those adapters stay config-selectable, not default)

## Decision

Card/detail covers become **two layered modes**, gated so the legally-clean one
is the only thing that can ever reach another person:

1. **`sprite` (the new default, shippable-safe).** Every recipe is assigned a
   `cover_sprite_id` from a catalog of **274 original neon-night-market SVG dish
   illustrations** (`frontend/src/covers/`, PRs #24/#27). Assignment folds into
   the existing extraction Gemini call — the model picks a `cover_sprite_id` from
   a compact catalog menu appended to the prompt — with a **deterministic
   keyword matcher** (over dish name / cuisine / tags) as the fallback when the
   model omits it or returns an unknown id. The sprite renders **inline** from
   the bundled asset (no `/image` endpoint, no blob, no storage). A generic
   `unknown-dish` cloche sprite is the final fallback, and a low-confidence /
   no-match assignment is appended to a new **`cover_misses`** table (input for a
   future "cover gardener" dev pass — NOT built here). In `sprite` mode the
   illustration job is **not** enqueued (zero paid image calls).

2. **`video_frame` (PRIVATE, off by default).** During extraction the Gemini
   call also returns the **timestamp of the best finished-dish beauty shot**;
   ffmpeg (already in the image) grabs that one frame and stores just the JPEG
   as the recipe's `image_url` (fits `MEDIA_RETENTION=discard` — the video is
   still discarded; heuristic ~90%-through fallback if no timestamp). Real
   frames are a **per-user, owner-granted** capability: a new
   `users.real_covers_enabled` flag (default OFF, settable only by the admin/
   owner) AND a global `CHEFCLAW_REAL_COVERS` switch (default OFF) must BOTH be
   true for a frame to be captured or served. **Precedence:** real frame (if
   allowed & available) → else sprite.

Real frames NEVER reach an ungranted viewer: `has_image` and the `/image`
endpoint are both **viewer-aware** — a real-frame `image_url` is projected/served
only when the global switch is on AND the requesting owner is granted; otherwise
the recipe reads as sprite-only. New schema (one migration off `e2f3a4b5c6d7`):
`recipes.cover_sprite_id`, `users.real_covers_enabled`, and the `cover_misses`
table.

## Why

- **Sprites are original art we own — zero legal risk, cross-servable, uniform.**
  The 274 SVGs were authored in the locked neon-night-market style (never traced
  from photos), so unlike a retained keyframe (a literal reproduction) they are
  freely ours to ship, redistribute, and relicense. Making them the DEFAULT
  means the shippable/multi-user path is legally clean by construction. The
  generated-Gemini-illustration cover (the 2026-07-06 design ADR) is **demoted
  from default to an optional `gemini` mode**: it cost a paid call per recipe and
  added an image job to the serial queue for a single-user library where a
  keyword-assigned sprite is free, instant, and on-brand. `fake` stays for the
  golden/test blob path.
- **Assignment folds into a call we already pay for.** The extraction Gemini
  call already emits `cuisine_type` + `tags`; adding a `cover_sprite_id` choice
  (from a compact id→name→tags menu) is a near-zero marginal cost and no new
  paid call. The **deterministic matcher is the load-bearing safety net** — it
  is the ONLY assignment path for the fake extractor, the backfill, and any
  model miss, so the system never depends on the model getting the id right.
  Rejected: a separate paid classification call (needless spend) and a
  frontend-only heuristic (the backend must assign so the id is stored once,
  authoritative, and identical on card + detail + backfill).
- **Runtime never writes to the repo; the library grows via a reviewed dev
  pass.** A miss logs to `cover_misses` and falls back to `unknown-dish` — no
  per-recipe generation, no server→GitHub push (that would bypass branch
  protection + CI + the human-merge gate, a §5 / Hard Rule 5 hole). The
  gardener that consumes the log is a separate, PR-gated dev session (not built
  here); the miss-log is the only seam it needs.
- **Real frames are private personal-use sharing, not a product feature —
  double-gated and removable.** Per Braeden's framing (v2 plan §V2-F): a
  removable layer over sprites for himself + a named handful, killable at zero
  cost. Two independent gates (`CHEFCLAW_REAL_COVERS` global + per-user
  `real_covers_enabled`) both default OFF, so the safe default is **pure
  sprites, no capture, no serving** — the fake test suite and any un-granted
  deployment can never surface a creator frame. The security-critical invariant
  ("a frame never reaches an ungranted viewer") is enforced at the projection
  AND the serving endpoint, not just the UI, and is future-proof: a hypothetical
  cross-served projection carries the *viewer's* grant (OFF for a public
  viewer), so multi-user/public mode is sprite-only by construction. Because
  today's reads are owner-scoped, the current viewer IS the recipe owner, so the
  gate reduces to "this owner's grant" — but it is written viewer-aware so it
  stays correct if recipes are ever cross-served.
- **The frame fits `discard` retention.** The beauty-shot timestamp rides the
  extraction response (no second model call); ffmpeg grabs one frame from the
  still-in-scratch video before it's discarded, and only the ~40 KB JPEG is
  kept. It's 480p and may carry a watermark — fine for a private thumbnail.
- **One migration, stable schema.** `cover_sprite_id`, `real_covers_enabled`,
  and `cover_misses` all land together off the real head `e2f3a4b5c6d7` so the
  shape is stable even though the real-frame capture defaults off.

Accepted tradeoffs: two catalogs (the canonical `frontend/src/covers/catalog.json`
for inline rendering + a byte-identical backend copy for assignment) kept honest
by a drift test, mirroring the openapi.json discipline. And a real-frame capture
path the fake test suite cannot exercise end-to-end (no real video / Gemini /
ffmpeg) — its gates, precedence, and heuristic are unit-tested with a fake
frame-grabber; the true capture is a documented human-precondition, exactly like
the real Gemini image model.

## Verified

- **Backend unit tier** (`uv run pytest -q -m "not golden"`, no DB): 415 pass.
  New coverage — the deterministic matcher (`red-braised-pork`/`margherita-pizza`
  exact, unmatchable → `None`, never returns the fallback), assignment precedence
  (valid model id trusted; unknown model id / no-match → `unknown-dish` + a typed
  miss), the catalog **drift test** (backend copy byte-identical to the frontend
  source), sprite mode assigns `cover_sprite_id` + enqueues NO illustration job +
  zero image spend, real-frame capture behind an injected fake grabber (uses the
  model timestamp; OFF by default → no capture), `backfill_sprites` assigns +
  logs a miss, viewer-aware `has_image` hides a frame from an ungranted owner
  (list + detail), `/image` 404s a private frame for an ungranted viewer, the
  owner-only admin users list + grant PATCH (403 for a non-admin, 422 on an extra
  field). `uv run ruff check .` clean.
- **Golden DB tier** (`-m golden`, throwaway postgres): 31 pass — real SQL for the
  atomic store writing `cover_sprite_id` (no illustration job in sprite mode),
  `record_cover_misses` + `set_recipe_sprite` via the backfill, and
  `list_recipes_for_frame_backfill` scoped by the per-user grant (the `User`
  join). The existing illustration-job DB tests kept green by pinning
  `chefclaw_image_generator="fake"`.
- **Migration** applied against real PG18: full chain to head `c3f0a1b2d4e5`;
  `downgrade -1` → `upgrade head` roundtrips cleanly; `alembic check` reports **No
  new upgrade operations detected** (models ↔ migration in lockstep).
- **Contract**: `backend/openapi.json` re-exported + `frontend/src/client`
  regenerated (new `cover_sprite_id`, `UserAdmin*` types, `/api/admin/users`);
  the drift generators are idempotent.
- **Frontend** (`vitest`): 111 pass incl. new CoverImage coverage — inline sprite
  render without a fetch, `unknown-dish` as the assigned fallback, unknown id →
  gradient, served image wins over sprite, and an errored served image falls back
  to the SPRITE (not the gradient). Typecheck / ESLint / Prettier clean; the
  golden selectors (`data-cover-fallback`, `role=img` + alt) are unchanged.

**Human preconditions before real frames:** set `CHEFCLAW_REAL_COVERS=true` (the
global switch) AND grant specific users via `PATCH /api/admin/users/{id}`
(`{"real_covers_enabled": true}`); both default OFF. Real-frame capture also needs
the real Gemini extractor (for the beauty-shot timestamp) + ffmpeg — the fake test
suite cannot exercise the true capture end-to-end (only the gating, precedence, and
timestamp heuristic are unit-tested).

**Deferred, with triggers:** the "cover gardener" dev pass that consumes
`cover_misses` to author new sprites (a separate PR-gated session — this PR lands
only the miss-log seam); a small admin-UI toggle for the real-frame grant (the
owner-only endpoint exists; today set via the API); gating/hiding the legacy
"Regenerate illustration" detail control in sprite mode (a no-op there, harmless).
