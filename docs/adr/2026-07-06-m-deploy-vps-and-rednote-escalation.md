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
