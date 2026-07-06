# Runbook

Operational procedures for the running chefclaw stack. Companions: `docs/SETUP.md`
(commands, env contract), `docs/SERVICES.md` (provisioning, which store holds what),
`docs/SECURITY.md` (incident + key-rotation runbooks). The stack's health surface is
`GET /api/health` — it is **not** auth-exempt, so read it through the Settings screen
or with `curl -s -H "Authorization: Bearer $CHEFCLAW_API_TOKEN" http://127.0.0.1:8000/api/health`
(the token resolves from your shell env; never paste its value inline).

---

## 1. Rednote access & cookie refresh (tiered — never the main account)

Access policy (plan amendment, 2026-07-06 — supersedes everything earlier):
**Braeden's main account never enters the pipeline under any circumstances** — no
cookie, no session, no fallback-to-main. Tiers, in order:

| Tier | What | When |
|---|---|---|
| **0 — guest (DEFAULT)** | No account, no cookie at all. Verified working against a real public note (2026-07-06). | Always, until a needed note actually fails |
| **1 — hard-isolated throwaway** | Disposable account in a dedicated browser profile (below). | Only for content guest can't fetch |
| **2 — manual file upload** | `LocalFileSource`: save the video yourself, upload with provenance URL. | Zero-platform-risk floor — extraction never *requires* platform access |

### Reading the health signal

`/api/health` → `cookie_freshness`, derived from `XHS_COOKIE_SET_DATE`
(thresholds in `backend/src/chefclaw/app.py`):

| Value | Meaning | Action |
|---|---|---|
| `not_configured` | No cookie set — **tier 0, the healthy default state** | None. This is not a problem to fix. |
| `fresh` | Cookie younger than 14 days | None |
| `aging` | 14–20 days old | Refresh soon — the warning fires *before* the 2–4-week expiry window closes |
| `stale` | ≥ 21 days old, or the date is unparseable | Refresh now (or drop back to tier 0 by clearing the cookie vars) |

A mid-job expiry surfaces as a typed `cookies_expired` job error pointing here.

### Cookie refresh procedure (tier 1 ONLY)

This procedure applies **only** when a tier-1 hard-isolated throwaway account is in
use. It is never performed with the main account — if the throwaway is banned or
lost, that is an accepted, disposable outcome; make a new one or fall back to tier 2.

1. Open the **dedicated browser profile** — one that has *never* been logged into
   the main account (and the throwaway is never installed in the phone app beside
   it). If such a profile doesn't exist, create it before creating the account.
2. Log in as the throwaway at xiaohongshu.com and browse a page so requests flow.
3. DevTools → **Network** tab → select any request to `xiaohongshu.com` → copy the
   full `Cookie` request-header value.
4. In the **same profile**, DevTools Console: run `navigator.userAgent` and copy the
   result. Cookie and UA must be captured together as a **matching pair** — the
   adapter sends both, and a cookie presented under a different UA looks like a
   stolen session.
5. Paste both into `.env.local` **yourself** (`XHS_COOKIE`, `XHS_USER_AGENT`).
   This is a human-only step by design — Claude is hook-blocked from every
   `.env*` file and must never see the values.
6. Set `XHS_COOKIE_SET_DATE=<today, YYYY-MM-DD>` in `.env.local` — **by hand, at
   every refresh**. Cookie age is not derivable from the cookie string; this date
   is the only thing the health warning has.
7. Restart the api so the new env applies:
   `docker compose --env-file .env.local up -d api`
8. Verify: `/api/health` reports `cookie_freshness: "fresh"`.

### Paste full share links (`xsec_token` is required)

XHS rejects token-less URLs — **bare note-id URLs always fail** (spike-verified
against XHS-Downloader v2.7). Always paste the **full share link**; the adapter
keeps its `xsec_token` on the fetch URL only, while dedupe stays on the token-free
note id.

**Deleted note vs missing token are indistinguishable** — the platform returns the
same message for both, so the error cannot tell you which happened. On a rednote
fetch failure: first re-copy a *fresh* full share link and retry; only if that also
fails conclude the note is gone (tier 2 won't help — there's nothing left to save).

---

## 2. Backups & restore

### What `scripts/backup.sh` does

Strictly **read-only against the running stack** (the local compose volumes are
production — kit inversion, `docs/SECURITY.md`); it never stops, restarts, or
writes to any production container or volume:

- **DB:** `pg_dump` via `docker compose exec -T postgres` (plain redirect, no
  pipeline — a truncated dump cannot fake success) → `gpg --symmetric
  --cipher-algo AES256`. The passphrase reaches gpg on fd 3, never argv or stdout.
- **Media:** the `chefclaw_chefclaw_media` volume tarred by a throwaway
  `docker run --rm … :ro alpine` container (volume existence pre-checked — a bare
  `-v` would silently create an empty volume and back up nothing) → gpg the same way.
- **Retention:** the newest **14** artifacts of each kind; older ones pruned.
- **State:** writes `ops/last-backup.json` (basenames + byte counts only, no paths,
  no secrets; `ok:false` + non-zero exit on any failure). The api reads it via the
  read-only `./ops:/data/ops:ro` mount and reports `/api/health` `backup`:
  `fresh` (last run ok, < 26 h old) / `stale` (old, failed, or unreadable) /
  `not_configured` (no state file yet — i.e. backups have never run here).
- **Config** (`.env.local`, resolved at runtime; an already-exported shell var
  overrides it): `CHEFCLAW_BACKUP_DIR` (where artifacts land — e.g.
  `<your-backup-destination>`, ideally a synced/off-machine location),
  `BACKUP_GPG_PASSPHRASE`, `CHEFCLAW_BACKUP_INCLUDE_MEDIA` (default `1`; set `0` to
  skip the media archive — the script warns when the archive passes 1 GiB).

Run it by hand from the repo root: `sh scripts/backup.sh`.

### The passphrase rule

`BACKUP_GPG_PASSPHRASE` is **generated once and stored in the password manager
FIRST** — that is the canonical copy. `.env.local` holds only the operational copy
the script reads. It must never exist *only* on this machine: a passphrase stored
solely beside the backups it encrypts protects against nothing (disk dies → backups
and key die together).

### Install the launchd schedule (human — an unscheduled backup script is not a backup)

```bash
cp ops/com.chefclaw.backup.plist.example ~/Library/LaunchAgents/com.chefclaw.backup.plist
$EDITOR ~/Library/LaunchAgents/com.chefclaw.backup.plist   # replace ALL THREE /Users/yourname/chefclaw paths
launchctl load ~/Library/LaunchAgents/com.chefclaw.backup.plist
launchctl start com.chefclaw.backup                        # run once now to verify
```

Then check `ops/backup.log` (gitignored) and confirm `/api/health` reports
`backup: "fresh"`. It runs daily at 03:30 local time. launchd runs a missed
schedule on wake only if the Mac was *asleep* at 03:30 — not if it was shut down —
and failure detection is pull-only, so the health readout is the backstop that
catches silently-missed runs either way.

> **On the VPS** (no launchd): the systemd equivalents are
> `ops/chefclaw-backup.service.example` + `ops/chefclaw-backup.timer.example`
> — install steps in the service file's header; see §4 step 9.

### Restore procedure

**Never restore into the production stack.** Restores go into a throwaway
container: unique name, non-default port, tmpfs/ephemeral storage, no production
volumes.

1. Decrypt the newest DB artifact (gpg prompts for the passphrase — read it from
   the password manager; never put the value on a command line):

   ```bash
   gpg -d -o /tmp/chefclaw-restore.sql "<your-backup-destination>/chefclaw-db-<stamp>.sql.gpg"
   ```

2. Start a throwaway Postgres (PG 18 images want the mount/tmpfs at
   `/var/lib/postgresql`, not `…/data`):

   ```bash
   docker run -d --name chefclaw-restore-<date> \
     -p 127.0.0.1:55434:5432 --tmpfs /var/lib/postgresql \
     -e POSTGRES_USER=chefclaw -e POSTGRES_PASSWORD=<throwaway-only> \
     -e POSTGRES_DB=chefclaw postgres:18-alpine
   ```

3. Load the dump, failing loudly on any error:

   ```bash
   psql -h 127.0.0.1 -p 55434 -U chefclaw -d chefclaw \
     -v ON_ERROR_STOP=1 -f /tmp/chefclaw-restore.sql
   ```

4. Verify against production (production side is **read-only** `SELECT`s via
   `docker compose exec postgres psql …`): `count(*)` for `users`, `recipes`,
   `jobs`, `llm_spend` must match, plus a content check (e.g. an md5 aggregate
   over recipe id+title, and the `llm_spend` cost sum) on both sides.
5. Media: decrypt the media artifact the same way, `tar -tzf` to list, extract a
   sample file, and compare its SHA-256 against the original in the volume (read
   the original via a throwaway `docker run --rm -v chefclaw_chefclaw_media:/src:ro
   alpine` container — read-only, never the api container).
6. Clean up: `docker rm -f` the throwaway container, delete the plaintext dump and
   extracted media from `/tmp`.

### Restore drill — RECORD (performed for real, 2026-07-06)

- **When:** 2026-07-06T18:52–18:54Z. Production stack untouched (all reads
  read-only; all three services stayed up throughout).
- **Backup run:** `chefclaw-db-20260706T185241Z.sql.gpg` = **8,474 bytes**;
  `chefclaw-media-20260706T185241Z.tar.gz.gpg` = **46,049,889 bytes**; exit 0.
- **Restore target:** throwaway `postgres:18-alpine`
  (`chefclaw-drill-pg-20260706`, 127.0.0.1:55434, tmpfs, `ON_ERROR_STOP`).
- **Row counts (production / restore):** users **1/1**, recipes **2/2**,
  jobs **8/8**, llm_spend **10/10**.
- **Content checks:** recipe id+title md5 aggregate
  `3ed63bf8a51712782865d6249af6fd4b` on both sides; `llm_spend` cost sum
  `0.201346` on both sides.
- **Media round-trip:** both sampled files SHA-256-identical to the volume
  originals —
  `bilibili/BV1sW4y1L73v-p1/BV1sW4y1L73v_p1.mp4` =
  `b8001630bb5fb6804cec76df4c5d17da7737b7ab17dd970b3aa7039337d7d19f`;
  `rednote/64c3190f000000000800d08e/64c3190f000000000800d08e-0.mp4` =
  `7434ee7ddcef33f6618f01d59393f7cf6f1eee980624c9926a721184615b6bf9`.
- **Cleanup:** drill container, scratch files, and the drill's throwaway
  passphrase deleted; the drill's `ops/last-backup.json` was removed so
  `/api/health` honestly reports `not_configured` until real scheduled backups
  exist.
- **Independently re-run 2026-07-06T19:19Z** (adversarial ops review, fresh
  throwaway passphrase + container on 55435): fresh artifacts 8,469 /
  46,049,889 bytes, exit 0; all row counts, both content checks, and both
  media SHA-256s reproduced identically; same cleanup performed. (This re-run
  also corrected the rednote sample path above — the archive nests media under
  `<platform>/<canonical_id>/`.)

---

## 3. Sidecar debugging (XHS-Downloader)

- **It has no host port — by design, not by accident.** Its API is
  unauthenticated; publishing it would let any LAN peer or any webpage in a
  browser drive the Rednote session. There is nothing to `curl` from the host:
  debug it with `docker compose logs` / `docker compose exec` only, and never add
  a `ports:` mapping "temporarily".
- **Logs are safe to read:** `docker compose logs xhs`. Verified 2026-07-06
  (spike): the sidecar's logs carry note ids only — **no cookie echo**.
- **Never log or print raw sidecar response bodies.** The response's `params`
  field echoes the request back **including the cookie**. The adapter parses only
  `data`; hand-debugging must do the same — print `message` / status codes, never
  the whole body.
- **Reachability:** `/api/health` → `sidecar` (`ok` / `unreachable` /
  `not_configured`). To probe from inside the compose network:

  ```bash
  docker compose exec api python -c \
    "import httpx; print(httpx.get('http://xhs:5556/docs').status_code)"
  ```

- **The image is digest-pinned** (`joeanamier/xhs-downloader@sha256:7ce9c4e7…`, see
  `compose.yaml` / `docs/SERVICES.md` §4). Bumping it is a **deliberate PR** that
  updates the pin *and* the adapters ADR
  (`docs/adr/2026-07-06-source-and-extractor-adapters.md`) — the sidecar contract
  (`POST /xhs/detail`, `download:false`, response shape) must be re-verified
  against the new version, never casually retagged.

---

## 4. Deploy (VPS + Tailscale)

Turn-key procedure for the M-Deploy posture (ADR:
`docs/adr/2026-07-06-m-deploy-vps-and-rednote-escalation.md`): a Hetzner-class
VPS, **Tailscale-first access, zero public exposure** — every published port
stays `127.0.0.1`-bound on the VPS (compose.yaml already does this) and
`tailscale serve` fronts the api toward the tailnet only. Install commands
below were verified current against the official docs on 2026-07-06; re-verify
on deploy day if months have passed.

1. **Provision** *(you, in dashboards)*: Hetzner Cloud → new CX-class server
   (a CX22-tier shared vCPU box is plenty for single-user), **Ubuntu LTS**,
   SSH key auth (no password login). Record the date/host in
   `docs/SERVICES.md` §7.
2. **Install Docker Engine + compose plugin** (official apt repo —
   docs.docker.com/engine/install/ubuntu):

   ```bash
   sudo apt update && sudo apt install ca-certificates curl
   sudo install -m 0755 -d /etc/apt/keyrings
   sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
   sudo chmod a+r /etc/apt/keyrings/docker.asc
   sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
   Types: deb
   URIs: https://download.docker.com/linux/ubuntu
   Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
   Components: stable
   Architectures: $(dpkg --print-architecture)
   Signed-By: /etc/apt/keyrings/docker.asc
   EOF
   sudo apt update
   sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   ```

3. **Install Tailscale** (official apt repo — pkgs.tailscale.com; the URLs
   below are the Ubuntu 24.04 "noble" ones — substitute your release codename):

   ```bash
   curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
   curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list | sudo tee /etc/apt/sources.list.d/tailscale.list
   sudo apt-get update && sudo apt-get install tailscale
   sudo tailscale up   # prints an auth URL — approve it in the admin console
   ```

4. **Clone the repo** to the documented path (the systemd units and this
   runbook assume it): `sudo git clone https://github.com/<owner>/chefclaw /opt/chefclaw`.
5. **HUMAN creates `/opt/chefclaw/.env.local` on the server** (Claude is
   hook-blocked from `.env*` everywhere, including here). Exactly these vars
   (contract + placeholders: `.env.example`):
   - `CHEFCLAW_API_TOKEN` — fresh token, not the local dev one
   - `GEMINI_API_KEY`
   - `MONTHLY_LLM_BUDGET_USD` + `MAX_EXTRACTION_ATTEMPTS_PER_DAY` (fail-closed pair)
   - `CHEFCLAW_BACKUP_DIR` + `BACKUP_GPG_PASSPHRASE` (backup pair — passphrase
     from the password manager, never generated on the VPS alone; point the
     dir OFF the VPS, see the ADR's backup note)
   - `MEDIA_RETENTION`
   - `SENTRY_DSN` + `VITE_SENTRY_DSN` + `SENTRY_ENVIRONMENT=vps` (observability
     — V2-A ADR; empty DSNs are legal and simply disable Sentry)
   - optionally `DB_PASSWORD` (postgres stays loopback-bound either way)
6. **Start the stack** — export the release SHA first so Sentry events carry
   the deployed commit (plain `up -d --build` without it works too, just
   untagged):

   ```bash
   cd /opt/chefclaw
   GIT_SHA=$(git rev-parse --short HEAD) sudo -E docker compose --env-file .env.local up -d --build
   ```

   — then confirm nothing listens publicly: `ss -tlnp | grep -E '8000|5432'`
   must show only `127.0.0.1`. Logs are structured JSON on stdout: read them
   with `sudo docker compose logs -f api` (each line carries method/path/
   status/latency for requests, job_id/stage for worker events).
7. **Front the api toward the tailnet** (syntax verified 2026-07-06;
   Tailscale auto-provisions the TLS cert — if HTTPS certificates aren't
   enabled for the tailnet yet, the command tells you and links the console
   toggle):

   ```bash
   sudo tailscale serve --https=443 --bg 127.0.0.1:8000
   tailscale serve status        # verify; `sudo tailscale serve --https=443 off` disables
   ```

8. **Phone:** install the Tailscale app, sign in to the same tailnet, then
   open `https://<vps-hostname>.<tailnet>.ts.net` and paste the API token
   into the token gate once.
9. **Install the backup schedule** (systemd, not launchd — the VPS has no
   launchd): follow the header of `ops/chefclaw-backup.service.example`
   (copy both units to `/etc/systemd/system/`, enable the **timer**, run the
   service once by hand, check `journalctl -u chefclaw-backup.service`).
10. **Verify end-to-end:** Settings screen all green — api reachable over the
    tailnet URL, sidecar `ok`, budget readout present, backup `fresh` after
    the step-9 manual run. Then paste one real link per platform; **watch the
    rednote job especially** — this is the first datacenter-IP test of the
    guest tier (see §5 if it degrades).

---

## 5. Rednote escalation ladder (operator playbook)

Posture (plan amendment §16.11, ADR
`2026-07-06-m-deploy-vps-and-rednote-escalation.md`): rednote-from-datacenter
is **test-first — fix on actual breakage, never pre-buy**. The failure plan is
prepared, not improvised: every rung is pure config, and rungs b/c/d are the
same single knob (`CHEFCLAW_FETCH_PROXY`).

### Recognizing degradation

The signature is **platform-shaped, not job-shaped**:

- Jobs drawer: `download_failed` (or guest-tier `cookies_expired`) errors
  **concentrated on rednote jobs while bilibili jobs keep succeeding**. That
  split is the datacenter-IP signal — a broken network would fail both.
- One-off failures are normal (deleted note vs missing `xsec_token` — §1);
  degradation means *fresh share links for known-public notes* fail
  repeatedly.
- `/api/health` stays green throughout (sidecar `ok` — the sidecar is
  reachable; it's the *platform* refusing the sidecar's datacenter IP).

Confirm before escalating: re-fetch one known-good public note with a fresh
share link. If it works, it was note-level, not IP-level — stay put.

### The rungs (in order; stop at the first one that restores service)

| Rung | What | Config change (the entire fix) |
|---|---|---|
| **a — tier-2 phone upload** | Zero prep, works regardless of server IP: browse Rednote on the phone (residential by definition), save the video, upload via the web UI with the provenance URL. | **None.** This works today; use it while deciding whether b/c/d are worth it. |
| **b — home exit node** | An existing always-on home device (Apple TV tvOS 17+ / NAS / a Tailscale-capable router) becomes a tailnet **exit node**; the VPS runs a userspace-networking `tailscaled` SOCKS5 proxy pointed at it, so platform fetches exit from the home residential IP. | On the VPS: run a second, userspace-networking `tailscaled` with `--socks5-server=:1055` (e.g. the `tailscale/tailscale` container attached to the compose network), then select the exit node with `tailscale set --exit-node=<home-device>` — an `up`/`set` flag, **not** a `tailscaled` one (flag split verified against tailscale 1.98.8). Then in `.env.local`: `CHEFCLAW_FETCH_PROXY=socks5://<proxy-host>:1055` and `docker compose --env-file .env.local up -d api`. |
| **c — commercial residential proxy** | Paid residential proxy via the same knob. **Gray-market caveat recorded in the ADR**: residential-proxy IP sourcing is ethically murky — a last resort before d, not a default. | `.env.local`: `CHEFCLAW_FETCH_PROXY=<provider URL>` (any credentials in that URL make it a secret — `.env.local` only, never anywhere else), restart the api. |
| **d — home-relay endpoint** | The original seam: run the fetch path itself on a residential-IP home device joined to the tailnet — move the xhs sidecar home and point the api at it. | `.env.local`: `XHS_SIDECAR_URL=http://<home-device-tailscale-ip>:5556` (tailnet traffic only — never expose the sidecar publicly), plus `CHEFCLAW_FETCH_PROXY` at a home proxy if the CDN media downloads are also IP-gated; restart the api. |

### Knob mechanics (what `CHEFCLAW_FETCH_PROXY` actually touches)

- Routes **platform-fetch traffic only**: the sidecar detail call's per-request
  `proxy` param (the sidecar dials the proxy itself), the api's media
  downloads and short-link resolution, and yt-dlp. The api→sidecar hop and
  DB/API traffic stay direct.
- Because the **sidecar dials the proxy too**, the proxy address must be
  reachable from *both* the api and xhs containers — put a proxy container on
  the compose network rather than on the host loopback.
- `socks5://` URLs: the api's httpx ships with socks support
  (`httpx[socks]`); yt-dlp handles socks natively. The pinned sidecar image
  was inspected (2026-07-06, throwaway container): its `ExtractParams` model
  declares `proxy` (the per-request param is honored, not silently dropped)
  and it ships httpx 0.28.1 + socksio 1.0.0, so socks5 *client construction*
  works there too. **End-to-end socks5 through the sidecar is still
  unverified** — if rung b fails inside the sidecar, front the SOCKS5 with a
  small HTTP proxy (note the result in the ADR).
