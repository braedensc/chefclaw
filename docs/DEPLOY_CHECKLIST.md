# Deploy readiness checklist (M4 — public hosted service)

The single ordered go/no-go list for taking chefclaw from localhost to a
**public, invite-only, upload-only hosted service** (milestone M4). It sits on
top of the mechanics in [`RUNBOOK.md`](RUNBOOK.md) §4 (deploy steps) and §5
(Rednote ladder) and the decisions in the ADRs
[`…-path-b-multi-user-product`](adr/2026-07-07-path-b-multi-user-product.md) and
[`…-m-deploy-vps-and-rednote-escalation`](adr/2026-07-06-m-deploy-vps-and-rednote-escalation.md)
(see its "M4 amendment" section for the public-TLS decision).

**Posture in one line:** auth is the security boundary (Google OAuth + opaque
sessions, M2); a Caddy reverse proxy terminates HTTPS on a real domain in front
of `127.0.0.1:8000`; **80/443 are public, 8000/5432 stay loopback-only**; the
hosted product is **upload-only** (no link-paste / platform fetch — that stays
self-host-only per Path-B). This supersedes the V2-B "Tailscale-private, zero
public exposure" endgame; Tailscale-private remains the documented interim/dev
option.

Everything below marked **[HUMAN]** needs a real account, secret, or
provisioning action and is queued for Braeden — Claude does not (and by the
hooks cannot) do these. Claude's engineering/doc prep is already landed (this
file, RUNBOOK §4 public-TLS path, the multi-arch note, the session-aware
`scripts/prod-smoke.sh`, the `.env.example` auth block, the ADR amendment).

---

## Gate 0 — code prerequisites (must land BEFORE public exposure)

These are **application-code** dependencies, not deploy steps. A public deploy
that skips them is unsafe or off-strategy. None block a **Tailscale-private,
single-user** interim deploy — they gate opening the door to *other people*.

- [ ] **Upload-only hosted-mode carve** — ⚠️ **NOT SHIPPED.** Path-B decision 1
      makes the hosted service upload-only, but no config gate disabling
      `POST /api/recipes/extract` (link-paste) + the Bilibili/Rednote source
      adapters exists yet (`chefclaw_sources=real` registers them
      unconditionally; both `/extract` and `/upload` are live). **Until this
      lands, an invited user on a public instance could drive platform fetches
      from the server — the exact operator-side ToS/redistribution posture
      Path-B exists to avoid.** Land the carve (its own PR) before inviting
      anyone but yourself to a public instance.
- [ ] **M3 — per-user budget caps.** M2 shipped the `users.monthly_budget_usd` /
      `max_attempts_per_day` columns *added-but-unused*; `spend.check_budget`
      still reads the **global** env budget, so all users share one pool. Before
      inviting friends, land M3 (per-user caps) or a single guest can exhaust the
      whole monthly LLM budget. (Task dependency note.)
- [ ] **V2-D — security audit** completed against the deployed surface (auth,
      admin routes, invite gate, upload endpoint, public exposure). (Task
      dependency note.)
- [ ] Worker concurrency is still **1** (no TaskIQ multi-worker step). The
      idempotent paid-call gate is only safe at concurrency 1 — if that ever
      changes, the double-spend gate must move into the claim transaction FIRST
      (Path-B pre-commitment).

> **Interim path:** a **Tailscale-private, single-user** deploy (RUNBOOK §4
> Option B) is safe without Gate 0 — it's just you, over the tailnet, with the
> full pipeline. Use it to exercise the stack while Gate 0 items land.

---

## Gate 1 — provisioning **[HUMAN]** (accounts, secrets, DNS)

Do these in dashboards before deploy day; record dates/choices in
[`SERVICES.md`](SERVICES.md) §7.

- [ ] **VPS** — a ≥ 2 GB RAM, Ubuntu LTS, x86 server (Hetzner CX22 recommended;
      Lightsail / DigitalOcean / Linode / Vultr all fine). SSH-key auth only.
- [ ] **Domain + DNS** — register a domain; add an **A** record (and **AAAA** if
      the VPS has IPv6) → the VPS public IP; let it propagate before step 7.
- [ ] **Google Cloud OAuth client** — create an OAuth 2.0 Client (Web), set the
      **authorized redirect URI** to `https://<domain>/api/auth/google/callback`
      *(exact match — a mismatch is the #1 OAuth failure)*. Capture the client id
      + secret for `.env.local`.
- [ ] **Transactional email (invites)** — AWS SES (or Resend) with a **verified
      sender** and out of the SES sandbox if inviting external addresses. Capture
      `EMAIL_FROM` + `SES_REGION`; SES send creds via the instance IAM role.
- [ ] **Sentry project + DSN** — free tier; one project; copy the DSN for
      `SENTRY_DSN` + `VITE_SENTRY_DSN`.
- [ ] **Off-VPS backup destination** — decide where `CHEFCLAW_BACKUP_DIR` points
      (tailnet copy home, or object storage — artifacts are gpg-encrypted at
      rest). A backup beside the data it protects doesn't survive host loss.
- [ ] **Backup passphrase** — `BACKUP_GPG_PASSPHRASE` generated and stored in the
      password manager FIRST (canonical copy); `.env.local` holds only the
      operational copy.

---

## Gate 2 — author the VPS `.env.local` **[HUMAN]**

Human-only (hook-blocked for Claude). Full contract + placeholders:
[`.env.example`](../.env.example); the per-line var list is RUNBOOK §4 step 5.
Non-negotiables for a `vps` deploy:

- [ ] `SENTRY_ENVIRONMENT=vps` — this is the prod signal. It **forces**
      `CHEFCLAW_AUTH_PROVIDER=google` **and** `CHEFCLAW_EMAIL=ses`; the container
      **fails to boot** (`auth.assert_prod_auth_safe`) if either is still `fake`.
      This is intentional fail-closed behavior, not a bug.
- [ ] `CHEFCLAW_AUTH_PROVIDER=google` + `GOOGLE_OAUTH_CLIENT_ID` /
      `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT_URL`.
- [ ] `CHEFCLAW_EMAIL=ses` + `EMAIL_FROM` + `SES_REGION`.
- [ ] `PUBLIC_BASE_URL=https://<domain>` (no trailing slash).
- [ ] `BOOTSTRAP_ADMIN_EMAIL=<your Google email>` — so YOUR first sign-in claims
      admin + the existing library. Empty ⇒ bootstrap-claim disabled.
- [ ] Fresh `CHEFCLAW_API_TOKEN` (legacy — no longer gates requests, but set it).
- [ ] `GEMINI_API_KEY`; the fail-closed budget pair `MONTHLY_LLM_BUDGET_USD` +
      `MAX_EXTRACTION_ATTEMPTS_PER_DAY`; the backup pair; `SENTRY_DSN` +
      `VITE_SENTRY_DSN`; `MEDIA_RETENTION`.
- [ ] **No secret is ever echoed, committed, or given a `VITE_*` prefix** (Hard
      Rules 2 & 4). The OAuth **secret** is server-only.

---

## Gate 3 — deploy day (ordered) **[HUMAN]**

Follow [`RUNBOOK.md`](RUNBOOK.md) §4 in order:

1. [ ] Provision + harden the VPS (§4 step 1).
2. [ ] Install Docker Engine + compose plugin (step 2).
3. [ ] Clone to `/opt/chefclaw` (step 4). *(Tailscale path: also step 3.)*
4. [ ] Author `.env.local` (Gate 2 above / step 5).
5. [ ] `alembic upgrade head` on the prod DB (via the compose `migrate` service
       on `up`, or `docker compose run --rm migrate`). Confirm the M2 revisions
       applied and the seed-admin row exists.
6. [ ] `GIT_SHA=… docker compose --env-file .env.local up -d --build` (step 6);
       build native on the box (multi-arch note only if cross-building).
7. [ ] `ss -tlnp | grep -E '8000|5432'` shows **only** `127.0.0.1` (step 6).
8. [ ] TLS ingress — **Option A: Caddy** (`/etc/caddy/Caddyfile` → `reload`) for
       public; **Option B: `tailscale serve`** for interim (step 7).
9. [ ] Backup schedule via systemd units (step 9); run once by hand; confirm
       `journalctl -u chefclaw-backup.service` and `/api/health` `backup: fresh`.
10. [ ] **You** sign in with Google FIRST (step 8) → confirm bootstrap-claim
        adopted admin + the library (`GET /api/me` shows `is_admin: true`).

---

## Gate 4 — acceptance (go/no-go before inviting anyone)

Run the scripted smoke check (RUNBOOK §4 step 10) and confirm each:

- [ ] `scripts/prod-smoke.sh https://<domain> <public-ip>` → **PASS**:
  - [ ] SPA index returns **200**.
  - [ ] `/api/health` is **401 without a session** (the load-bearing assertion —
        health exposes spend/cookie/backup state and is NOT publicly exempt).
  - [ ] With `CHEFCLAW_SESSION=<your cookie>`: `/api/health` **200**, `db: ok`,
        `worker: alive`.
  - [ ] Public-port scan: **8000 and 5432 closed** on the public IP.
- [ ] TLS cert valid (`curl -sI https://<domain>/` → `HTTP/2 200`); HTTP→HTTPS
      redirect works; Caddy auto-renewal confirmed enabled.
- [ ] Session cookies are **Secure** (derived from `vps`) — verify in DevTools.
- [ ] An **invite** email actually arrives (SES out of sandbox / recipient
      verified) and its link activates a second account end-to-end.
- [ ] A **non-invited** Google sign-in is refused with a single opaque 403 (no
      account created).
- [ ] One recipe added end-to-end: **upload** a saved video (hosted/upload-only)
      → extracts to a card.
- [ ] Restore drill performed **on the VPS** (RUNBOOK §2) and the backup lands
      **off-VPS**.

---

## First-real-exercise flags (unverified-live until deploy day)

These have **never run against their real services** — expect first-run
surprises and budget time to debug at deploy, not after inviting people:

- **Google OAuth** end-to-end (login → callback → session) — only ever exercised
  through the `FakeOAuthProvider` in tests.
- **AWS SES** invite delivery — only the console/fake adapter has run.
- **Qwen/DashScope fallback** extractor — region/data-governance review is itself
  a human precondition before first real use (SERVICES §3).
- **Sidecar SOCKS5** (Rednote escalation rung b) — client construction is
  verified; end-to-end socks5 through the sidecar is not (RUNBOOK §5). Only
  relevant to the self-host/Tailscale full pipeline, not the upload-only product.

---

## Abort / rollback

- **Bad deploy:** `docker compose down` stops containers; **named volumes
  survive** (never `down -v`). Fix `.env.local` / image, `up -d --build` again.
- **Pull the door shut fast:** `sudo systemctl stop caddy` (public) or
  `sudo tailscale serve --https=443 off` (tailnet) removes ingress instantly
  while the stack keeps running loopback-only.
- **Compromise / key leak:** rotate the affected secret in `.env.local` +
  provider dashboard, `up -d api` to reload; revoke sessions by deleting rows
  from `sessions` (instant, server-side — the reason M2 chose opaque sessions).
  Full runbook: [`SECURITY.md`](SECURITY.md).
