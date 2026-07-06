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
