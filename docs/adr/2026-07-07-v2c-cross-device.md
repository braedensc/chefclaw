# V2-C cross-device: mobile-responsive pass + installable PWA

**Date:** 2026-07-07 · **Context:** V2-C part 1 (v2 plan §V2-C mobile/web polish half), branch `feat/v2c-cross-device`

## Decision

Make chefclaw feel like a phone app without building one. Three moves, all inside
the already-landed neon night-market design system (apply it, don't restyle):

1. **Responsive pass over every screen** at a 375 px phone floor and desktop.
   Touch targets reach ≥44 px **on coarse pointers only** via two `@media (pointer:
   coarse)` utilities (`tap-target` for text buttons/links, `tap-field` for
   inputs/selects) — so the compact desktop mouse UI is byte-for-byte unchanged and
   only phones/tablets get the bigger hit areas. Every golden/smoke semantic
   selector (roles + accessible names) is preserved.
2. **Jobs drawer becomes a bottom sheet on mobile** (slides up from the bottom edge,
   rounded top, `max-h`-capped, tap-scrim to dismiss) and stays the right-hand
   sidebar at `≥sm`. Still one `<aside aria-label="Jobs">` (`role=complementary`),
   so the golden selector contract holds; the slide-up is reduced-motion-guarded.
3. **PWA:** a hand-written `public/manifest.json` (standalone display, night-black
   theme, maskable + apple-touch icons rasterized from the puppy-chef mark) plus a
   **manual, dependency-free** service worker (`public/sw.js`) — app-shell
   navigation is network-first with an offline fallback, hashed static assets are
   cache-first, and **`/api/*` is never touched by the cache** (auth/session and
   owner-scoped images must always hit the network). Registered prod-only, with a
   standard lifecycle (no `skipWaiting`/`clients.claim`) so the SPA is never
   controlled on its first load. A phone-viewport Playwright project joins the
   LOCAL-ONLY golden suite alongside the desktop one.

## Why

- **Apply, don't restyle.** V2-E already shipped the design system as tokens
  precisely so the mobile pass inherits it (v2 plan §V2-E sequencing note). This PR
  adds responsive *classes* and coarse-pointer touch floors; it changes no colors,
  type, or component shapes.
- **Coarse-pointer touch targets, not blanket 44 px.** WCAG 2.5.5 wants ≥44 px on
  touch; making every compact caps-button 44 px tall on desktop too would bloat the
  deliberately-tight mouse UI. Gating the enlargement on `(pointer: coarse)` gives
  phones the hit area and leaves desktop pixel-identical — and it maps exactly onto
  the test matrix (Pixel 5 = coarse, Desktop Chrome = fine). Rejected: a global
  size bump; per-button `max-sm:` overrides (viewport ≠ input modality — a
  fine-pointer small laptop would get needless bulk).
- **Bottom sheet is the native mobile idiom.** A full-height right rail reads as a
  desktop slide-over even on a phone; a bottom sheet with a grab handle and a
  tap-scrim is what a phone user expects, and it keeps the close button + scroll in
  thumb reach. The single `<aside>` (same accessible name) means zero test churn.
- **Manual SW over vite-plugin-pwa.** The plan allowed either; manual wins here for
  three reasons this repo cares about: (a) **zero new dependency** on a public
  AGPL repo whose CI/e2e run offline; (b) the cache policy is **auditable in ~40
  lines** — most importantly the explicit `/api` bypass, which a security-conscious
  app must guarantee (never cache a session or an owner-scoped image), rather than
  trusting Workbox defaults; (c) runtime cache-first handles Vite's content-hashed
  filenames without a build-time precache manifest. Rejected: vite-plugin-pwa
  (dependency + generated Workbox SW is harder to eyeball for the `/api` guarantee).
- **Prod-only, uncontrolled-first-load registration.** Dev (Vite HMR) never
  registers; the smoke suite runs a prod `vite preview` build, so the SW *does*
  register there — but with a standard lifecycle (no `clients.claim`) the
  registering page is never controlled, so the single-navigation smoke and golden
  specs are unaffected. Trade-off accepted: SW updates apply on the next-next load,
  fine for a personal single-user app.
- **Icons from the existing mark, not a new asset.** A dedicated full-bleed square
  `app-icon.svg` (puppy-chef head on night-black, content inside the maskable safe
  zone) is rasterized to 192/512/maskable/180 PNGs with `qlmanage` (macOS,
  no new tooling). The master SVG is committed so the PNGs are reproducible.

## Verified

- **Every screen at 375 px + desktop**, driven by Playwright against the isolated
  golden stack (fake auth + fake adapters, tmpfs — never the real stack): Library
  (grid/empty/paste bar/filters), Recipe detail (hero, ingredients + 原文 toggle,
  steps, raw-JSON drawer), Jobs (bottom sheet on mobile / sidebar on desktop),
  Settings, and the login/invite cards. Before/after screenshots in the PR.
- **Touch targets (measured):** under a Pixel 5 (coarse) the "Jobs" header
  control and the search field both render at **44 px**; the same "Jobs" control
  on desktop (fine pointer) stays **29 px** — proving the enlargement is scoped to
  touch and desktop is untouched. `matchMedia('(pointer: coarse)')` is `true` on
  the phone, `false` on desktop.
- **Mobile upload path:** the "Upload video" control is a `<button>` that clicks a
  hidden `<input type="file" accept="video/*">` — on a phone browser this opens the
  native picker (camera roll + record), the §16.10 tier-2 floor; no `capture`
  attribute (which would force the camera and block picking a saved Rednote video).
- **PWA / service worker (runtime-verified against the prod build on :8100):**
  `/manifest.json` and `/sw.js` both serve 200; after registration + reload the
  SW controls the page, the shell cache holds `/` + manifest + icons, the assets
  cache holds the hashed JS/CSS/woff2, and **no `/api/*` path appears in any
  cache** — the invariant. Manifest carries name/short_name/start_url/standalone/
  theme+background and a 512 maskable icon; `<link rel="manifest">` +
  apple-touch-icon + apple-mobile-web-app meta are in `index.html`.
- **Golden suite** (LOCAL-ONLY — cannot run in CI): the same paste→card spec passes
  under both the `desktop` and new `mobile` (Pixel 5) projects. **Note in the PR:**
  CI runs Vitest + the Playwright *smoke* only; the mobile golden is exercised
  locally, like the rest of the golden suite.
- CI tiers stay green: `typecheck` / `lint` / `format:check` / Vitest / the
  build + Playwright smoke (login gate + SW registration on the prod preview).
