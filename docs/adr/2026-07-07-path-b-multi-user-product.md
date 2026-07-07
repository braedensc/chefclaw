# Path B: hosted multi-user product (upload-only, invite-only)

**Date:** 2026-07-07 · **Context:** product-direction decision opening the multi-user milestone (M1); grounded in the multi-user feasibility & legality audit (2026-07-06, `planning/`). Supersedes the "single-user-only until a dedicated ADR" hold the audit left open.

## Decision

chefclaw becomes a **hosted, multi-user product** — invite-only, starting with a small circle of friends, growing over time. Four decisions fix its shape:

1. **The hosted service is UPLOAD-ONLY.** Users upload videos they saved themselves; the server **never fetches from Bilibili/Rednote**. Link-paste + platform fetch (yt-dlp, the XHS sidecar, cookies, the fetch-proxy ladder) remains **self-host-only** — available to anyone running their own copy, absent from the shared service. This is Path B from the audit; it is the boundary that keeps the operator out of the platform-ToS / redistribution category.
2. **Auth = social OAuth** (Google first, Apple/others addable) — no passwords stored by us.
3. **Signup is invite-only, with owner-sent invites.** The owner (admin) enters an email in-app and the system emails that person an invite; only an invited email can activate an account (OAuth sign-in is gated on a matching pending invite). This needs an `invites` table, an admin-only invite endpoint, a transactional-email adapter, and an admin/role flag on `users`.
4. **No interim personal deploy.** Localhost stays the owner's personal setup until the product itself deploys (M4).

**Phasing** (each its own ADR/PR):
- **M1** — this decision ADR. First implementation step after it: carve the hosted app to upload-only (a config-gated "hosted mode" that disables link-paste + the platform source adapters, leaving the upload path).
- **M2** — accounts & invites: OAuth login + invite-gated signup + owner invite flow (admin endpoint + email adapter) + login/signup UI replacing the token gate.
- **M3** — per-user guardrails: per-user budget/rate-limit caps (`users` columns into `check_budget`), Gemini **paid** tier, owner-scoped media serving.
- **M4** — public deploy: real domain + TLS on the 2 GB Lightsail host (auth is the boundary now; Tailscale-private is superseded for the product).
- **Deferred until load/growth needs it:** the TaskIQ job-worker graduation (the serial worker is fine for a few friends; **the double-spend gate must move into the claim transaction before a second worker ever runs**); payments + operating entity + a counsel session when charging.

## Why

- **Legality is the gate, not hosting** (audit). It forks on *who fetches the content*: user-supplied uploads put chefclaw in the mature "process what the user gives us" category (DMCA 512(c) fits; no operator-side ToS breach), whereas fetching-for-others (Path C) matches the decided Chinese unfair-competition fact pattern and invites payment-processor freezes. Free-vs-paid barely moves this; personal-vs-serving-third-parties is the step change.
- **Upload-only is also a simplification**: the hosted product sheds the sidecar, yt-dlp, cookie tiers, and the proxy ladder — less to run and secure.
- **Social OAuth over passwords**: nothing to store, reset, or breach; friends already have Google/Apple; more providers are additive. Rejected email+password (storage + reset + verification surface) and magic-link (needs the same email infra as invites but weaker than OAuth) as the *primary* method.
- **Invite-only + owner-sent emails** is the owner's explicit requirement — precise control over who joins, self-serve activation for them. It also caps growth to a rate the single-worker backend can serve, deferring the concurrency rebuild honestly.
- **The foundation is real** (code inventory): `owner_id` is on every user-owned row from migration #1, every CRUD query is owner-scoped, and `require_owner` is a genuine swappable seam — the service layer doesn't change when its internals become real identity.

## Verified

This is a direction-setting ADR; its evidence is the audit's sourced legal analysis + the code inventory (auth seam, owner-scoped CRUD, the per-owner spend ledger). Per-phase verification lands with each phase's PR. Two correctness pre-commitments recorded now so they can't be forgotten: (1) dedupe (`find_active_job` / `find_completed_job_with_recipes` / `find_recipe_ids` + the `UNIQUE(platform,canonical_id,dish_index)` constraint) is currently **not owner-scoped** — a cross-tenant metadata leak that M2 must close; (2) the idempotent paid-call gate is safe **only at worker concurrency 1** — it must move into the claim transaction before any TaskIQ multi-worker step, or the double-spend race the whole design exists to close reopens.
