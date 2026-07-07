# Design system & brand: neon night-market, puppy chef, real video covers

**Date:** 2026-07-06 · **Context:** V2-E design revamp (v2 plan §V2-E), first V2-E PR

## Decision

chefclaw's UI adopts a **"neon night-market" design system** — true-black base with
neon-halo accents (platform identity: bilibili = electric cyan, rednote = chili pink,
local = warm white), condensed-caps Latin display type over ZH-first bilingual titles —
landed as **Tailwind v4 `@theme` tokens** plus a small set of brand components. The
mascot is the **claw-family puppy chef** (the same real dog behind todoclaw's icon, in
a toque), not a food-themed character. Recipe cards and the detail page carry **real
poster frames extracted from the retained source video**: after the recipes are
stored, a best-effort ffmpeg stage writes one JPEG per dish into the media archive
and updates `cover_path` per recipe; covers are served owner-scoped via
`GET /api/recipes/{id}/cover` (the SPA fetches them through the generated client into
blob URLs — `<img>` alone cannot authenticate).

## Why

- **Direction by bake-off, not committee:** three throwaway single-screen mockups
  (warm-rustic / neon night-market / clean editorial, in gitignored
  `planning/design-bakeoff/`) were screenshotted and put to Braeden; he picked neon
  night-market as the base and pulled in the storybook puppy mascot and the
  simmering-pot job chip from the warm-rustic direction. A day of exploration beat
  committing blind (kit spike/bake-off pattern).
- **Covers were the highest-leverage "uninformative" fix:** the source video is already
  retained (`MEDIA_RETENTION=keep`) and ffmpeg is already in the api image (DASH
  merge), so real covers cost one worker stage — no new service, pennies of storage.
  Multi-dish videos get frames at `duration * (i+1)/(N+1)` so sibling cards differ.
  **Best-effort, outside the paid-work window:** covers run AFTER the atomic store —
  a hung ffmpeg or a crash can never delay or lose paid extraction (the recipe is the
  product, the cover is garnish); a failure logs and leaves `cover_path` NULL. The
  one-shot startup backfill (a non-blocking background task) is the reconciler for
  both pre-existing recipes and any store-then-crash gap. Covers come only from the
  retained archive — `MEDIA_RETENTION=discard` writes nothing to the media volume,
  as discard promises. Rejected: thumbnails via the extractor model (paid,
  unnecessary); public/static serving (violates owner-scoping — covers go through
  the authed route with the path `resolve()`d under `media_dir`);
  covers-inside-the-store-transaction (aesthetic atomicity is not worth coupling the
  paid path to ffmpeg). Accepted tradeoff: a permanently corrupt archived video is
  re-attempted once per process start, bounded by the 30s subprocess timeouts —
  revisit with a persisted attempted-marker if boot logs ever show repeated backfill
  failures.
- **Card facts come from the validated document, never invented:** `RecipeSummary`
  gains `has_cover` / `difficulty` / `total_time_minutes` / `ingredient_count` —
  difficulty and time lifted verbatim; `ingredient_count` is the structural length
  of the ingredients list (a count of entries, not a food quantity — Hard Rule 7
  governs food data like amounts and weights). The filesystem `cover_path` is never
  exposed in the API.
- **Type that respects both languages:** ZH dish names lead (system CJK stacks —
  PingFang SC on Apple devices, Noto fallback elsewhere; a CJK webfont would cost
  megabytes for no gain on the owner's devices), with self-hosted Barlow Condensed
  (@fontsource, bundled, no CDN — CI/e2e run offline and prod stays same-origin) for
  the Latin display voice. Rejected: webfont CJK, CDN fonts.
- **Restyle inside the accessibility contract:** every golden-suite/smoke selector
  (roles + accessible names: `Video link`, `Extract`, `原文`, `Jobs`, `Save token`,
  `Stored` in the drawer, the token-gate sentence, etc.) is unchanged — the golden
  suite stays the regression net. Job chips got bilingual cooking-stage microcopy;
  the jobs drawer deliberately keeps the sober `statusLabel` vocabulary (it is the
  ops surface, and golden asserts it).
- **Motion is opt-out by construction:** every animation (steam wisps, neon flicker,
  pup bob/wave, marquee) lives behind `prefers-reduced-motion: no-preference`.

## Verified

- Backend: `uv run pytest -q` green (26 new tests: cover stage happy/failure/multi-dish
  fractions, backfill grouping, `/cover` 200/404/traversal, summary projections);
  `ruff` clean; `openapi.json` re-exported and the typed client regenerated in the
  same PR (drift job).
- Frontend: typecheck / lint / format / Vitest green (new brand-component and
  cooking-stage tests); Playwright smoke green (token-gate contract intact).
- Golden paste→card suite run locally against the isolated `chefclaw-golden` stack
  (fake adapters; exercises the new migration + selectors end-to-end).
- Every screen state (library grid/empty/loading/error, token gate, chips
  active/failed, detail, drawer, settings) screenshotted at 1280px and 380px and
  reviewed against the mockups.

**Deferred, with triggers:** user-uploaded photos of the *cooked* dish on the recipe
(trigger: Braeden asks again post-V2-C; needs an upload surface + a second image slot —
explicitly wanted 2026-07-06); smarter cover frame selection (scene detection) if the
fraction heuristic picks dull frames in practice; PWA/manifest polish belongs to V2-C.
