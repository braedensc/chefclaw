# AGPL-3.0 licensing & kit attribution

**Date:** 2026-07-05 · **Status:** Accepted · **Context:** bootstrap (Phase 0), public repo

## Decision

chefclaw is licensed **AGPL-3.0-or-later**; sole copyright holder Braeden
Collins. The top-level `LICENSE` carries the AGPL text; the root
`package.json` `license` field is the SPDX id `AGPL-3.0-or-later`; every
future manifest (backend `pyproject.toml`, `frontend/package.json`) declares
the same id.

The repo is instantiated from the MIT-licensed `braedensc/claude-project-kit`
template. MIT nests cleanly inside an AGPL work: a top-level **`NOTICE`** file
preserves the kit's complete MIT license text and credits the kit for the
derived files (hooks, CI, docs skeleton).

## Why

- **The license is the monetization lever, not visibility.** Public code
  doesn't give away a service business — the sellable asset is a hosted
  service, users, and brand, not source. AGPL makes hosting a rival service off
  this code legally unattractive (network use requires opening changes). As
  sole copyright holder, **dual-licensing later** stays open: AGPL for the
  public, commercial terms for anyone who wants out of AGPL. The one-way door
  avoided: MIT is irrevocable for anyone who forks, so starting MIT and later
  wanting AGPL is the costly mistake; starting AGPL costs ~nothing.
- **Honest note for any future business ADR:** the real monetization blockers
  are a crowded consumer food/health market with low willingness-to-pay and
  the scraping/ToS legal exposure of a *company* redistributing platform
  content — not repo visibility. A sellable version likely shifts the
  monetizable surface away from scraping (users bring their own links; charge
  for the intelligence over their recipes). That is a lawyer conversation if
  the day comes.
- **Public-repo posture is a net win:** GitHub secret scanning, push
  protection, and Dependabot are free on public repos and are on from day one;
  the kit's local layers remain the first line. Nothing personal is ever
  committed, and the personal-use posture toward platform ToS is stated
  plainly in the security docs.
- **Alternatives rejected:** MIT (forecloses dual-licensing, see above);
  private repo (loses free server-side scanning, and secrecy protects nothing
  the license doesn't protect better).

## Verified

`LICENSE` is the AGPL-3.0-or-later text; `NOTICE` contains the kit's full MIT
license text with attribution to `braedensc/claude-project-kit`; the root
`package.json` `license` field matches the LICENSE file — all landing in the
bootstrap PR. Phase-1 manifests must carry the same SPDX id (checked at PR
review).
