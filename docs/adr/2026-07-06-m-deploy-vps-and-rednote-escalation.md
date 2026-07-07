# M-Deploy: VPS + Tailscale posture & the Rednote escalation ladder

**Date:** 2026-07-06 · **Context:** M-Deploy preparation (branch
`feat/m-deploy-prep`; plan §9 M-Deploy as amended by §16.11, Braeden
2026-07-06). Prep only — no VPS exists yet; everything here is config, docs,
and templates so deploy day is turn-key.

## Decision

Deploy the compose stack to a **cheap Hetzner-class VPS** (Ubuntu LTS), with
**Tailscale-first access and zero public exposure**: every published port stays
`127.0.0.1`-bound on the VPS (compose.yaml already binds them so), fronted by
`tailscale serve` toward the tailnet only — TLS via Tailscale's auto-provisioned
certs when wanted. **The MacBook is not a server** (it travels).
**Rednote-from-datacenter is TEST-FIRST**: deploy, paste a real rednote link,
and fix on *actual* breakage — but with the failure plan **prepared, not
improvised**. The escalation ladder, in order:

- **(a) tier-2 phone upload** — zero prep, works regardless of server IP: the
  user browses Rednote on a residential phone and uploads saved videos via the
  web UI (`LocalFileSource`, shipped in Phase 2/3).
- **(b) home exit node via an existing device** (Apple TV tvOS 17+ / NAS /
  Tailscale-capable router) — a userspace-networking Tailscale SOCKS5 proxy on
  the VPS pointed at the home exit node, plus the fetch-proxy knob.
- **(c) commercial residential proxy** via the same knob (gray-market
  IP-sourcing caveat recorded below).
- **(d) home-relay endpoint** — the original seam: the xhs sidecar moves to a
  residential-IP home device on the tailnet (`XHS_SIDECAR_URL` is already
  config).

Every rung is **pure config**. The enabling seam ships in this prep PR:
`CHEFCLAW_FETCH_PROXY` routes **only platform-fetch traffic** — the sidecar
detail call's per-request `proxy` param, the api's media downloads and
short-link resolution, and yt-dlp's `proxy` opt. The api→sidecar hop
(compose-internal) and DB/API traffic are never proxied. Rungs b, c, and d all
turn this one knob (d additionally re-points `XHS_SIDECAR_URL`). Operator
playbook — how to recognize degradation and the exact change per rung:
`docs/RUNBOOK.md` §5.

Backups run **on the VPS** via systemd units
(`ops/chefclaw-backup.service.example` + `.timer.example` — the VPS has no
launchd), daily 03:30, journald logs, `Persistent=true` so a reboot across
03:30 still fires.

## Why

- **Tailscale-first** gives encrypted transport + network-layer auth for the
  phone use case at near-zero effort; nothing is internet-facing, so the
  public-exposure preconditions (real TLS management, token rotation) stay
  deferred (docs/SERVICES.md deferred-hardening table).
- **Test-first on Rednote** because the guest tier from a datacenter IP is
  *unknown*, not known-broken — paying for mitigation before observing a
  failure buys nothing. The ladder makes "fix on breakage" honest: each rung is
  a knob-turn, not a build.

**Alternatives rejected by name:**

- **MacBook-as-server** — it travels; a server that leaves the house nightly
  isn't one. (It remains the dev machine; the local stack stays the golden-
  suite target.)
- **Pre-buying a residential proxy** — spends money and takes on rung c's
  ethical caveat before any evidence the guest tier degrades.
- **Buying hardware for a home server / exit node** — rung b deliberately uses
  an *existing* device (Apple TV tvOS 17+, NAS, router); new hardware is only
  justified after rungs a–c prove insufficient, which is the opposite of prep.

**Accepted tradeoffs + future hardening:**

- **Guest-tier-from-datacenter is untested until deploy day** — accepted; the
  ladder is the hedge, and rung a works from day one regardless.
- **Rung c's caveat:** commercial residential-proxy IP sourcing is gray-market
  (SDK-bundled "peers" of dubious consent). Recorded so choosing it later is a
  conscious decision, after a and b.
- **The Docker-at-03:30 dependency changes shape:** launchd (best-effort,
  wake-only catch-up) becomes systemd `After=docker.service` +
  `Requires=docker.service` + timer `Persistent=true` on the VPS — strictly
  better, but the units are untested until a real host exists.
- **Backups must re-point off-VPS:** backups run *on* the VPS, so
  `CHEFCLAW_BACKUP_DIR` on the VPS must land **off-VPS** — options: a tailnet
  copy back to a home machine (e.g. rsync/`scp` over the tailnet after each
  run, or a mounted home share), or object storage (encrypted artifacts only —
  they're already gpg-encrypted at rest). A backup beside the data it protects
  survives software mistakes, not host loss. Decide the destination on deploy
  day; record it in docs/SERVICES.md §7.
- **Sidecar socks support partially verified:** the sidecar dials
  `CHEFCLAW_FETCH_PROXY` itself (per-request param). The pinned image was
  inspected in a throwaway container (2026-07-06): `ExtractParams` declares
  `proxy` — the param is honored, not silently dropped — and the image ships
  httpx 0.28.1 + socksio 1.0.0, so socks5 client construction works there.
  End-to-end socks5 through the sidecar stays unverified until rung b is
  actually needed (RUNBOOK §5 knob mechanics).

## Verified (what this prep PR proved vs what waits for deploy day)

**Proved now (2026-07-06, mocked tests + portability audit):**

- **Proxy seam, rednote:** with `CHEFCLAW_FETCH_PROXY` set, the sidecar payload
  carries `proxy`, the media-download client is constructed with `proxy=`, and
  the api→sidecar client stays direct; with it unset, no `proxy` key/kwarg
  anywhere (`backend/tests/test_sources.py`:
  `test_rednote_fetch_proxy_routes_platform_traffic_only`,
  `test_rednote_fetch_without_proxy_builds_direct_clients`,
  `test_rednote_short_link_resolution_uses_fetch_proxy`).
- **Proxy seam, bilibili:** yt-dlp opts carry `proxy` when set, absent when
  not; b23.tv short-link resolution is proxied too
  (`test_bilibili_fetch_proxy_passed_to_yt_dlp_when_set`,
  `test_bilibili_short_link_resolution_uses_fetch_proxy`).
- **socks5 URLs won't crash httpx:** `httpx[socks]` added to backend deps
  (yt-dlp handles socks natively); socks5 client construction exercised
  against the locked httpx 0.28.1. A malformed proxy URL fails at client
  construction with the password **masked** by httpx (`user:[secure]@…`) —
  no credential can leak into job errors or logs even on misconfiguration.
- **The sidecar honors the per-request `proxy` param:** the pinned
  `joeanamier/xhs-downloader` image was inspected in a throwaway container —
  its `ExtractParams` pydantic model declares `proxy: str = None` (so the
  field is parsed, not silently ignored), and the image ships httpx 0.28.1 +
  socksio 1.0.0.
- **backup.sh portability:** audited line-by-line for BSD/GNU divergence —
  `date` uses only portable `-u '+FMT'` forms; `stat` already had the
  BSD→GNU→`wc -c` fallback chain; heredoc-on-fd-3, `tail -n +N`, and `$((…))`
  are POSIX. **No portability bugs found**; `dash -n` (Ubuntu's `/bin/sh`)
  parses it clean. The load-bearing constructs were also *executed* on
  ubuntu:24.04 (GNU coreutils + dash): `stat -f%z` fails rc=1 there so the
  fallback chain really falls through; the gpg 2.4.4 fd-3 loopback
  encrypt/decrypt round-trips; the `.env.local` parser and prune pipeline
  behave identically. Only macOS-slanted *messages* were updated.
- Both systemd unit examples are admitted by `.gitignore`'s `ops/*` negations
  (verified with `git check-ignore`).
- Install commands + `tailscale serve` syntax in RUNBOOK §4 verified against
  the official docs (docs.docker.com, pkgs.tailscale.com, tailscale CLI
  reference) on 2026-07-06 — and *executed* in a throwaway ubuntu:24.04
  container: both apt repos resolve, all packages install, and
  `tailscale serve --https=443 --bg 127.0.0.1:8000` (plus the `off` and
  `status` forms) is accepted by tailscale 1.98.8 (fails only at the
  expected no-daemon step). The rung-b flag split was verified the same way:
  `-socks5-server` belongs to `tailscaled`; `--exit-node` to
  `tailscale up`/`set`.

**Untested until deploy day (by design — this is prep):**

- Rednote guest tier from an actual datacenter IP (the whole point of
  test-first).
- The systemd units on a real host; `tailscale serve` against the real
  tailnet; the off-VPS backup destination choice.
- Every ladder rung beyond (a) — b/c/d exist as config paths, exercised only
  by the mocked seam tests above.

---

## M4 amendment (2026-07-07): public TLS ingress supersedes Tailscale-private for the product

**Context:** the Path-B ADR (`2026-07-07-path-b-multi-user-product.md`) turned
chefclaw into a hosted, invite-only, **upload-only** multi-user product, and its
M4 phase is "public deploy: real domain + TLS — auth is the boundary now,
Tailscale-private is superseded for the product." M2 shipped that boundary
(Google OAuth + opaque server-side sessions; `/api/health` is not auth-exempt).
This amendment records the ingress decision the original ADR deferred. It is
**engineering/doc prep** — no VPS, domain, or accounts exist yet; everything
account/secret-gated is queued in [`docs/DEPLOY_CHECKLIST.md`](../DEPLOY_CHECKLIST.md).

### Decision

1. **Public deploy terminates TLS with a reverse proxy — Caddy — on a real
   domain, in front of `127.0.0.1:8000`.** Caddy runs as a **host service** (not
   a compose service), so the compose stack stays entirely loopback-bound and
   Caddy is the only public listener. It auto-provisions and **auto-renews** a
   Let's Encrypt cert (no cron), does HTTP→HTTPS + HTTP/2, and forwards
   `X-Forwarded-Proto`. Mechanics: [`docs/RUNBOOK.md`](../RUNBOOK.md) §4 step 7,
   Option A. **nginx + certbot** is documented as a viable alternative for hosts
   already running nginx.

2. **The exposure model inverts from V2-B.** V2-B / the original decision above
   was "zero public exposure — nothing internet-facing." Under M4, **auth is the
   security boundary**, so the app is *meant* to be internet-reachable:
   **80/443 are public; 8000/5432 stay `127.0.0.1`-bound.** The
   `scripts/prod-smoke.sh` port scan still asserts 8000/5432 are closed publicly;
   the loopback invariant is unchanged, only what fronts it differs.
   `tailscale serve` (Option B) is retained as the **interim / dev / personal
   single-user** path — and is the *only* posture where the full link-paste +
   Rednote sidecar pipeline belongs (Path-B keeps platform fetch self-host-only).

3. **Host: provider-agnostic, ≥ 2 GB RAM, Ubuntu LTS, x86.** Hetzner CX22 stays
   the recommended host (cheapest with real headroom); Lightsail / DigitalOcean /
   Linode / Vultr are all viable — the Path-B ADR's "2 GB Lightsail host" was
   illustrative, not a hard pick. The public path additionally needs a **domain +
   DNS A/AAAA record**; the final host + domain choice is queued for provisioning
   (`docs/SERVICES.md` §7).

4. **Build stays native-on-host; cross-arch is `buildx` + QEMU.** `Dockerfile.api`
   builds for the VPS's own architecture when built on the box (the documented
   flow). Cross-building x86↔ARM (e.g. an Ampere/Graviton host, or building on an
   Apple-silicon Mac for an x86 host) uses `docker buildx --platform …` with the
   QEMU binfmt emulator; the base images are already multi-arch. Note:
   [`docs/RUNBOOK.md`](../RUNBOOK.md) §4 step 6.

### Why Caddy over nginx + certbot

For a single upstream needing "HTTPS on one domain, auto-renewed," Caddy is a
two-line Caddyfile with automatic ACME + renewal built in; nginx + certbot is a
hand-written server block plus certbot's separate renewal timer and reload hooks
— strictly more moving parts for no benefit at this scale. nginx wins only when
it's already deployed. Both keep the stack loopback-bound; the choice is
operational surface area, not capability. A container-based Caddy in compose was
rejected to avoid adding published `ports:` and cert volumes to the compose file
— a host service keeps compose's "all ports 127.0.0.1" invariant literally true.

### Gates (do NOT go public until these hold — full list in the checklist)

- **Upload-only hosted-mode carve (Path-B decision 1) — NOT shipped yet.** No
  config gate disables `POST /api/recipes/extract` + the platform source adapters
  in hosted mode; both `/extract` and `/upload` are live. A public instance today
  would let invited users drive server-side platform fetches — the operator-side
  ToS/redistribution posture Path-B exists to avoid. This carve is a prerequisite
  for public (not for a personal Tailscale-private instance).
- **M3 per-user budget caps** — M2 added the per-user columns but `check_budget`
  still reads the global env pool; without M3 one guest can drain the month's
  budget.
- **V2-D security audit** against the deployed surface.
- Ideally land M3 + V2-D + the carve before public exposure; this prep does not
  block on them (checklist Gate 0).

### Verified / unverified

This amendment is prep: the Caddy install + Caddyfile were authored against
Caddy's official docs (not executed on a real host); `scripts/prod-smoke.sh` was
re-worked to the M2 session-cookie model and exercised locally (parses clean
under `sh`/`dash`; hard-fails on an unreachable host; skips the authed leg
without `CHEFCLAW_SESSION`). **First real exercise at deploy day:** Google OAuth
end-to-end, SES invite delivery, the Qwen fallback, and sidecar SOCKS5 — none
have run against their live services (checklist "first-real-exercise flags").
