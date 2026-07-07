# Design system & brand: neon night-market, puppy chef, generated dish covers

**Date:** 2026-07-06 · **Context:** V2-E design revamp (v2 plan §V2-E), first V2-E PR

## Decision

chefclaw's UI adopts a **"neon night-market" design system** — true-black base with
neon-halo accents (platform identity: bilibili = electric cyan, rednote = chili pink,
local = warm white), condensed-caps Latin display type over ZH-first bilingual titles —
landed as **Tailwind v4 `@theme` tokens** plus a small set of brand components. The
mascot is the **claw-family puppy chef** (the same real dog behind todoclaw's icon, in
a toque), not a food-themed character.

Recipe cards and the detail page carry a **generated cartoon illustration of the dish**.
After the recipes are stored, a best-effort stage prompts a Gemini image model **from
the dish's text only** (name EN/中文, cuisine, ingredient *names* — never a video frame,
never a quantity), writes the JPEG into the media dir, and sets `image_url` per recipe;
images are served owner-scoped via `GET /api/recipes/{id}/image`. Cards also show two
**derived estimates** on distinct icons — `estimated_spiciness_level` (chilis) and
`estimated_difficulty_level` (a level meter), both 0–3, both flagged "estimated".

## Why

- **Direction by bake-off, not committee:** three throwaway single-screen mockups
  (warm-rustic / neon night-market / clean editorial, in gitignored
  `planning/design-bakeoff/`) were screenshotted and put to Braeden; he picked neon
  night-market as the base and pulled in the storybook puppy mascot and the
  simmering-pot job chip from the warm-rustic direction. A day of exploration beat
  committing blind (kit spike/bake-off pattern).
- **The cover is a *generated* illustration, not a video frame** (Braeden's revised
  2026-07-06 decision, `planning/chefclaw-cover-and-retention-decisions.md`). An
  illustration built only from unprotectable *facts* (dish name, cuisine, ingredient
  names) carries none of the source video's protected expression, so it stays
  **cross-servable** for the Path-B multi-user product — unlike a retained keyframe,
  which is a literal reproduction. It is also uniform across wildly-varying source
  videos. The build first shipped an **ffmpeg keyframe** cover (what the kickoff and
  the un-patched v2-plan §V2-E still described); on review the superseding decision
  surfaced and the covers were rebuilt as generated illustrations in the same PR.
  Because covers no longer come from the video, **`MEDIA_RETENTION` default flips to
  `discard`** — the source video is no longer retained by default (a small provenance
  frame remains a future option, never the card face).
- **Paid, but fail-closed and off the critical path:** image generation is a paid
  Gemini call, so it sits behind the same guardrails as extraction — the budget +
  daily-cap gate runs *before* the call, an `llm_spend` row is written per image
  (flat per-image cost, config), and no key ⇒ a typed `ConfigError` before anything
  bills. It runs **after** the atomic store (a hung/failed/over-budget image never
  delays or loses the recipe — `image_url` just stays NULL), and a non-blocking
  one-shot startup backfill reconciles image-less recipes. **Fake by default**
  (`CHEFCLAW_IMAGE_GENERATOR=fake`): CI, tests, and the golden suite never spend or
  touch the network; the real adapter is config-gated and its model id
  (`gemini-3.1-flash-image`) + per-image cost are flagged for human confirmation at
  deploy (image models sunset fast). Rejected: a separate `illustration` job type
  (the post-store best-effort stage reuses the reviewed cover machinery with far less
  surface — no new job/status/dispatch; independent per-recipe re-generation from the
  UI is a noted future option), and public/static serving (owner-scoping is kept via
  the authed route with the path `resolve()`d under `media_dir`).
- **Card facts: verbatim where possible, estimates flagged and kept separate.**
  `RecipeSummary` gains `has_image`, `total_time_minutes` (verbatim from the document),
  `ingredient_count` (the structural length of the ingredients list — a count of
  entries, not a food quantity), and two **derived** fields
  `estimated_spiciness_level` / `estimated_difficulty_level` (0–3). Per Hard Rule 7 the
  estimates live in a separate `estimated` column validated by its own strict
  `EstimatedAttributes` model (`source: "derived"`) — never inside the raw `document`,
  never overwriting a verbatim capture, the same posture reserved for nutrition. The
  extractor produces them as its only inferred numeric fields (prompt v2); they are
  **read-only** (not in `RecipePatch`) for now — an owner-editable classification is a
  noted future question. The filesystem `image_url` path is never exposed in the API.
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

- Backend: `uv run ruff check .` clean; `uv run pytest -q` green (image-generator
  selection/fail-closed, text-only prompt has no quantities, illustration stage
  happy/failure/over-budget still stores the recipe, estimated-fields split out of the
  document, `/image` 200/404, summary projections). `openapi.json` re-exported and the
  typed client regenerated in the same PR (drift job); grep confirms no
  `cover_path`/`/cover`/ffmpeg code remains.
- Frontend: typecheck / lint / format / Vitest green (new spiciness + difficulty scale
  tests, image-cover tests); Playwright smoke green (token-gate contract intact).
- Golden paste→card suite run locally against the isolated `chefclaw-golden` stack
  (fake extractor + fake image generator — zero spend/network; exercises the migration,
  the `/image` route, and the selectors end-to-end).
- Every screen state (library grid/empty/loading/error, token gate, chips
  active/failed, detail, drawer, settings) screenshotted at 1280px and 375px.

**Human preconditions before real images:** confirm the current Gemini image model id
and its real per-image price, set `CHEFCLAW_IMAGE_GENERATOR=gemini` + the keys in
`.env.local`, add the three new keys to `.env.example`, and run a 5–10 dish style pilot
before any full-library backfill (gated by the existing monthly/daily caps).

**Deferred, with triggers:** user-uploaded photos of the *cooked* dish (Braeden wants
this — needs an upload surface + a second image slot); a separate retriable
`illustration` job type if per-recipe re-generation from the UI is wanted
(**implemented 2026-07-07** — see [Illustration generation is its own retriable
job](2026-07-07-illustration-job-type.md)); ~~an owner-editable classification for the
two estimates~~ (resolved 2026-07-07 —
[Owner-editable estimates & the derived-vs-user merge posture](2026-07-07-owner-editable.md));
PWA/manifest polish (V2-C).
