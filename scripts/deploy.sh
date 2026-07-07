#!/bin/sh
# chefclaw push-based CD — on-box deploy driver (plan §deploy; canonical CD spec §3).
#
# Runs ON the Lightsail box (Ubuntu 24.04, login user `ubuntu`) as the FORCED
# COMMAND for the dedicated deploy SSH key. Because the authorized_keys entry
# pins command="/opt/chefclaw/scripts/deploy.sh",restrict,…, this script takes
# NO positional arguments — everything is read from /opt/chefclaw and its
# human-created .env.local. CI passes the target image DIGEST out-of-band as
# $SSH_ORIGINAL_COMMAND (the forced command ignores it AS a command; we validate
# it against a strict allowlist so a leaked, already-shell-less key cannot pick
# an arbitrary image or inject a command).
#
# BOX PREREQUISITES (one-time, human — see docs/RUNBOOK.md §4 CD setup and
# docs/DEPLOY_CHECKLIST.md Gate 5). deploy.sh runs as `ubuntu` with NO tty and
# CANNOT sudo, so the ubuntu user MUST be able to drive docker + git directly:
#   - ubuntu in the `docker` group   (sudo usermod -aG docker ubuntu; re-login)
#   - /opt/chefclaw owned by ubuntu  (sudo chown -R ubuntu:ubuntu /opt/chefclaw)
#   - git safe.directory set         (git config --global --add safe.directory /opt/chefclaw)
# Without these, the very first CD run fails at `docker compose pull`
# (socket EACCES) or `git merge` (dubious ownership) — see the preflight below.
#
# Flow (fail-closed at every rail):
#   0. validate the CI-supplied @sha256 digest → CHEFCLAW_IMAGE
#   1. capture the CURRENTLY-running api image as a PULLABLE rollback ref
#   2. backup FIRST via scripts/backup.sh (read-only vs the stack)
#   3. git fetch + ff-only sync (compose files / scripts / migration context)
#   4. docker compose pull (immutable digest; api + migrate share it) — never build
#   5. run DB migrations via the one-shot `migrate` service, gate on its exit code
#   6. up -d --no-build --no-deps the api (migrate already ran in step 5)
#   7. HEALTH-GATE: poll GET http://127.0.0.1:8000/ (SPA index, unauthenticated)
#   8. on failure → roll back to the captured previous image (--pull never), exit 1
#   9. on success → record the last-good digest + prune stale images
#
# SECURITY: never echoes secrets; .env.local is read ONLY by compose (--env-file)
# and by backup.sh's own parser — never sourced/eval'd here. NEVER eval or execute
# $SSH_ORIGINAL_COMMAND directly: it is untrusted input, validated as a digest only.
# The ssh exit status equals this script's exit status, so a failed health-gate or
# rollback reds the GitHub Actions deploy job.
#
# ROLLBACK ≠ SCHEMA REVERT: step 5 runs `alembic upgrade head` BEFORE the api
# swap. The health-gate rollback in step 8 reverts only the CODE (image), never
# the schema — alembic downgrade is NOT run. A destructive/backward-incompatible
# migration therefore leaves the rolled-back (old) api running against the NEW
# schema, and the SPA-index health gate can still pass (it is liveness-only).
# MITIGATION: keep migrations additive / backward-compatible with the immediately
# previous release (expand-then-contract); a bad migration requires a DB restore
# from the pre-deploy backup (docs/RUNBOOK.md §2). This is WHY /api/livez matters.
#
# Portability: POSIX /bin/sh (dash-safe, like scripts/backup.sh). set -eu.
# FUTURE: replace the static-mount-only health gate with GET /api/livez (a real
# db+worker readiness probe — its own ADR); add `cosign verify` on the digest
# before pull once images are signed (the digest handoff makes it a clean drop-in).

set -eu             # backup.sh uses -u only; a deploy WANTS abort-on-error (-e)
set +x              # defensive: never trace (a traced line could leak an env value)
umask 077
# The forced command runs with a minimal environment — make sure docker/git/curl
# are reachable. Appending keeps an interactive operator's own PATH authoritative.
PATH="${PATH}:/usr/bin:/usr/local/bin"
export PATH

REPO_DIR="/opt/chefclaw"
cd "$REPO_DIR"

COMPOSE="docker compose -f compose.yaml -f compose.prod.yaml --env-file .env.local"
HEALTH_URL="http://127.0.0.1:8000/"
HEALTH_RETRIES=30                        # 30 * 3s ≈ 90s
MEDIA_VOLUME="chefclaw_chefclaw_media"   # project-prefixed name (matches backup.sh)
LAST_GOOD_FILE="ops/last-deploy-image"   # persists the last successfully-served pullable ref
LOCK_FILE="ops/.deploy.lock"             # on-box mutex (Actions serializes too, but break-glass paths don't)

log()  { printf '%s deploy: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
fail() { log "FAIL: $*"; exit 1; }

# ── preflight (every refusal names the fix, never a value) ───────────────────
[ -f compose.yaml ] && [ -f compose.prod.yaml ] || fail "compose files missing (expected compose.yaml + compose.prod.yaml in $REPO_DIR)"
[ -f .env.local ] || fail ".env.local missing (human-created on the box; required)"
command -v docker >/dev/null 2>&1 || fail "docker not found on PATH"
command -v git    >/dev/null 2>&1 || fail "git not found on PATH"
command -v curl   >/dev/null 2>&1 || fail "curl not found on PATH"
# ubuntu must own the tree (git ff-merge + ops/ writes) and reach the docker
# socket (no sudo under a no-pty forced command). Fail LOUD with the fix, not
# with a cryptic EACCES three steps later.
mkdir -p ops || fail "cannot create ./ops — is $REPO_DIR owned by the deploy user? (sudo chown -R ubuntu:ubuntu $REPO_DIR)"
docker info >/dev/null 2>&1 || fail "cannot reach docker daemon — add the deploy user to the 'docker' group (sudo usermod -aG docker ubuntu; re-login)"

# ── on-box mutex: refuse to overlap with a concurrent/break-glass deploy ─────
# GitHub Actions serializes via concurrency:, but a manual SSH-with-a-digest or a
# hand-run `up -d --build` could interleave git-merge + image-swap. flock is the
# cheap guard. (flock is part of util-linux, present on Ubuntu 24.04.)
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || fail "another deploy is in progress (holding $LOCK_FILE) — retry after it finishes"
else
  log "flock not found — skipping on-box mutex (Actions concurrency still serializes CD runs)"
fi

# ── STEP 0 — validate the digest handed over by CI (untrusted input) ─────────
# CI sends the image digest as $SSH_ORIGINAL_COMMAND; the forced command ignores
# it as a command. STRICT allowlist: only a well-formed chefclaw @sha256 digest
# is accepted — never eval'd, never used as a shell command.
REQ="${SSH_ORIGINAL_COMMAND:-}"
case "$REQ" in
  sha256:*)                             IMAGE="ghcr.io/braedensc/chefclaw@${REQ}" ;;
  ghcr.io/braedensc/chefclaw@sha256:*)  IMAGE="$REQ" ;;
  *) fail "invalid image ref from CI (want sha256:… or ghcr.io/braedensc/chefclaw@sha256:…)" ;;
esac
printf '%s' "$IMAGE" | grep -Eq '^ghcr\.io/braedensc/chefclaw@sha256:[0-9a-f]{64}$' \
  || fail "image ref failed strict format check"
CHEFCLAW_IMAGE="$IMAGE"
export CHEFCLAW_IMAGE
log "target image: $CHEFCLAW_IMAGE"

# ── STEP 1 — capture a PULLABLE rollback ref (BEFORE any mutation) ────────────
# CRITICAL: `docker inspect {{.Image}}` returns a BARE local config id
# (sha256:<64hex>) which is NOT a pullable reference — feeding it back through
# compose (pull_policy: always) makes `docker pull sha256:<id>` fail
# ("pull access denied", the daemon reads it as docker.io/library/sha256:…), so
# the rollback would die exactly when it is needed. Instead we resolve a ref the
# registry (or a --pull never local lookup) actually accepts, in priority order:
#   1. the running container's RepoDigests[0] → ghcr.io/braedensc/chefclaw@sha256:…
#   2. the last-good digest we persisted after the previous successful deploy
#   3. the running container's .Config.Image (the CHEFCLAW_IMAGE compose set)
PREV_CID="$($COMPOSE ps -q api 2>/dev/null || true)"
PREV_IMAGE=""
if [ -n "$PREV_CID" ]; then
  PREV_IMAGE="$(docker inspect --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{end}}' "$PREV_CID" 2>/dev/null || true)"
  [ -z "$PREV_IMAGE" ] && PREV_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$PREV_CID" 2>/dev/null || true)"
fi
# Prefer a persisted digest if the container inspect gave us nothing usable.
if [ -z "$PREV_IMAGE" ] && [ -f "$LAST_GOOD_FILE" ]; then
  PREV_IMAGE="$(cat "$LAST_GOOD_FILE" 2>/dev/null || true)"
fi
# Only accept a rollback ref that is a real pullable digest ref — never a bare id.
case "$PREV_IMAGE" in
  ghcr.io/braedensc/chefclaw@sha256:*) : ;;
  *) [ -n "$PREV_IMAGE" ] && log "ignoring unusable rollback ref '$PREV_IMAGE' (not a pullable digest)"; PREV_IMAGE="" ;;
esac
log "previous api image (rollback ref): ${PREV_IMAGE:-<none>}"

# ── STEP 2 — BACKUP FIRST (safety rail #1) ───────────────────────────────────
# backup.sh does `docker compose exec -T postgres pg_dump`, so postgres must be
# UP. On a normal redeploy it is; if the operator previously `docker compose
# down`ed the stack, bring postgres up (data volume survives a plain down) and
# wait for healthy before backing up. backup.sh self-reads its own secrets
# (CHEFCLAW_BACKUP_DIR / BACKUP_GPG_PASSPHRASE) from .env.local — deploy.sh
# handles NO secrets. First-ever deploy: the media volume does not exist yet, so
# skip only the media leg.
if [ -z "$($COMPOSE ps -q postgres 2>/dev/null || true)" ]; then
  log "postgres not running — starting it before backup (data volume survives a plain 'down')"
  $COMPOSE up -d --no-build postgres || fail "could not start postgres for the pre-deploy backup"
  # wait for the compose healthcheck to report healthy
  j=0
  while [ "$j" -lt 30 ]; do
    st="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
          "$($COMPOSE ps -q postgres)" 2>/dev/null || echo starting)"
    [ "$st" = "healthy" ] && break
    j=$((j+1)); sleep 2
  done
fi
if docker volume inspect "$MEDIA_VOLUME" >/dev/null 2>&1; then
  sh scripts/backup.sh || fail "pre-deploy backup failed — aborting"
else
  log "media volume absent (first deploy) — backup without media leg"
  CHEFCLAW_BACKUP_INCLUDE_MEDIA=0 sh scripts/backup.sh || fail "pre-deploy backup failed — aborting"
fi

# ── STEP 3 — sync the repo (compose files + scripts + migration context) ─────
# Fast-forward ONLY: a non-ff tree means the box was hand-edited — abort rather
# than clobber. `git switch -C main --track origin/main` is robust to a detached
# HEAD or a missing local `main` (a fresh/shallow /opt/chefclaw clone), unlike a
# bare `git checkout main`. deploy.sh is already loaded into shell memory, so a
# mid-run change to this file applies only on the NEXT deploy (acceptable).
git fetch --prune origin || fail "git fetch failed"
git switch -C main --track origin/main 2>/dev/null || git checkout -B main origin/main \
  || fail "could not point local main at origin/main (is $REPO_DIR a clean clone owned by the deploy user?)"
git merge --ff-only origin/main \
  || fail "git not fast-forwardable — the box tree diverged. Recover: 'git fetch origin && git reset --hard origin/main' (preserve .env.local + gitignored ops/). NEVER hand-edit tracked files under $REPO_DIR."

# ── STEP 4 — pull the immutable image (api + migrate share $CHEFCLAW_IMAGE) ───
# Never build on the box; compose.prod.yaml pins image: for both services and
# deploy.sh never passes --build.
$COMPOSE pull || fail "docker compose pull failed for $CHEFCLAW_IMAGE"

# ── STEP 5 — run migrations via the one-shot migrate service (fail-closed) ────
# `run --rm migrate` executes the compose-defined command (alembic upgrade head
# && seed_fake_owner — the seed no-ops under CHEFCLAW_AUTH_PROVIDER=google from
# .env.local), gives a clean exit code, and pulls up its depends_on: postgres
# healthy first. Gate BEFORE the api swap so a bad migration never reaches a
# running api (the OLD api keeps serving). See the ROLLBACK ≠ SCHEMA REVERT note
# in the header — a bad migration's remedy is a DB restore, not an image roll.
$COMPOSE run --rm migrate \
  || fail "DB migration failed — aborting BEFORE api swap (old api still serving)"

# ── STEP 6 — bring up the new api WITHOUT building or re-running migrate ──────
# --no-deps: migrate already ran to completion in STEP 5; without --no-deps the
# api's `depends_on: migrate` would start a SECOND migrate run (idempotent but
# wasteful/confusing). --no-build: compose.prod.yaml pins image:, never build.
$COMPOSE up -d --no-build --no-deps --remove-orphans api || fail "compose up failed"

# ── STEP 7 — HEALTH-GATE on the unauthenticated SPA index ────────────────────
# GET http://127.0.0.1:8000/ → 200 proves the api process is alive and serving
# the static mount. LIVENESS ONLY — it does NOT prove the DB is reachable or the
# worker thread is alive; a boots-but-broken deploy can still pass. Do NOT probe
# /api/health — it is 401 by design (needs a session cookie). The real fix is a
# future unauthenticated /api/livez (db + worker probe, its own ADR).
i=0; healthy=0; code=000
while [ "$i" -lt "$HEALTH_RETRIES" ]; do
  # -w '%{http_code}' prints no newline, so `|| echo 000` would concatenate into
  # "000000"; use `|| code=000` which REPLACES (curl already prints 000 on a
  # connect failure). Keeps the retry log readable.
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_URL" 2>/dev/null)" || code=000
  [ "$code" = "200" ] && { healthy=1; log "health OK ($HEALTH_URL 200)"; break; }
  i=$((i+1)); log "health $code — retry $i/$HEALTH_RETRIES"; sleep 3
done

# ── STEP 8 — ROLLBACK on health-gate failure → exit non-zero (reds the job) ──
# The rollback image is already LOCAL (it was running seconds ago), so force
# `--pull never` to OVERRIDE compose.prod.yaml's `pull_policy: always` — a
# rollback must never depend on a fresh registry pull.
if [ "$healthy" -ne 1 ]; then
  log "HEALTH GATE FAILED (last code=$code) — rolling back"
  if [ -n "$PREV_IMAGE" ]; then
    CHEFCLAW_IMAGE="$PREV_IMAGE" $COMPOSE up -d --no-build --no-deps --pull never --remove-orphans api \
      || log "rollback up failed"
    sleep 3
    code2="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_URL" 2>/dev/null)" || code2=000
    log "post-rollback health code=$code2 (rolled back to $PREV_IMAGE)"
  else
    log "no previous image captured (first deploy) — cannot auto-rollback; MANUAL intervention needed"
  fi
  fail "deploy failed health gate for $CHEFCLAW_IMAGE"
fi

# ── STEP 9 — record last-good digest + reclaim disk (only AFTER a healthy gate)
# Persist the pullable digest so the NEXT deploy has a guaranteed rollback ref
# even if RepoDigests inspection ever comes up empty.
printf '%s\n' "$CHEFCLAW_IMAGE" > "$LAST_GOOD_FILE" 2>/dev/null || log "could not persist $LAST_GOOD_FILE (non-fatal)"
# Every deploy pulls a new digest and never reuses the old layers wholesale; on a
# small VPS the chefclaw image (python + ffmpeg + node build output) is large and
# would accumulate one-per-deploy until the disk fills and `pull` starts failing.
# Prune dangling images older than a week AFTER the health-gate/rollback path is
# fully done, so a rollback candidate is never yanked mid-deploy. Non-fatal.
docker image prune -f --filter 'until=168h' >/dev/null 2>&1 || log "image prune skipped (non-fatal)"

log "deploy OK — now serving $CHEFCLAW_IMAGE"
exit 0
