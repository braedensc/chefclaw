#!/bin/sh
# chefclaw backup — encrypted pg_dump + media-volume archive (plan §10).
#
# Recipes are irreplaceable: the LOCAL compose volumes are production (kit
# inversion, docs/SECURITY.md). This script is strictly READ-ONLY against the
# running stack: pg_dump over `docker compose exec` for the DB, and a
# throwaway `docker run --rm … :ro` container to tar the media volume. It
# never stops, restarts, or writes to any production container or volume.
#
# Config (environment; an already-exported var beats .env.local so a drill or
# one-off run can safely override without touching the human's env file).
# .env.local is PARSED for exactly the keys below, never shell-sourced or
# executed: it is a compose-format file, and compose-format values (cookies
# with spaces/semicolons, unquoted UA strings) are data — sourcing them would
# execute fragments and echo secret pieces into stderr/backup.log.
#   CHEFCLAW_BACKUP_DIR          required — where encrypted artifacts land
#   BACKUP_GPG_PASSPHRASE        required — symmetric key; generated once,
#                                lives in the password manager, NEVER printed
#   CHEFCLAW_BACKUP_INCLUDE_MEDIA  default 1 — 0 skips the media archive
#   DB_USER / DB_NAME            default chefclaw (match compose defaults)
#
# Outputs:
#   ${CHEFCLAW_BACKUP_DIR}/chefclaw-db-<UTC>.sql.gpg
#   ${CHEFCLAW_BACKUP_DIR}/chefclaw-media-<UTC>.tar.gz.gpg
#   ops/last-backup.json   (repo-root; bind-mounted read-only into the api so
#                           /api/health reports backup staleness — gitignored)
# Retention: the newest 14 of each artifact kind; older ones are pruned.
# Any failure ⇒ ops/last-backup.json records ok:false and the exit is non-zero.
#
# Scheduling: ops/com.chefclaw.backup.plist.example (launchd, daily 03:30).

set -u
set +x # defensive: never trace (a traced heredoc would print the passphrase)
umask 077

# launchd user agents get a MINIMAL environment (PATH=/usr/bin:/bin:/usr/sbin:
# /sbin) — docker and gpg live in the Homebrew/Docker-Desktop prefixes, so the
# scheduled run would otherwise fail every night. Appending (not prepending)
# keeps an interactive shell's own PATH authoritative.
PATH="${PATH}:/opt/homebrew/bin:/usr/local/bin"
export PATH

# Compose project + volume naming: compose.yaml sets `name: chefclaw`, so the
# media volume materializes as chefclaw_chefclaw_media (project prefix).
MEDIA_VOLUME="chefclaw_chefclaw_media"
KEEP_ARTIFACTS=14
MEDIA_WARN_BYTES=1073741824 # 1 GiB — nudge toward CHEFCLAW_BACKUP_INCLUDE_MEDIA=0

STATE_DIR="ops"
STATE_FILE="${STATE_DIR}/last-backup.json"

log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

# ── state file (written on success AND failure; no secrets, basenames only) ──
write_state() {
    # $1 ok(true|false)  $2 db_file  $3 media_file  $4 db_bytes  $5 media_bytes
    _db_json="null"
    [ -n "$2" ] && _db_json="\"$2\""
    _media_json="null"
    [ -n "$3" ] && _media_json="\"$3\""
    mkdir -p "$STATE_DIR" || return 1
    _tmp_state="${STATE_FILE}.tmp"
    printf '{\n  "finished_at": "%s",\n  "ok": %s,\n  "db_file": %s,\n  "media_file": %s,\n  "db_bytes": %s,\n  "media_bytes": %s\n}\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" "$_db_json" "$_media_json" "$4" "$5" \
        >"$_tmp_state" || return 1
    mv "$_tmp_state" "$STATE_FILE"
}

DB_FILE=""
MEDIA_FILE=""
DB_BYTES=0
MEDIA_BYTES=0

fail() {
    log "FAIL: $*"
    # Only write state where the api's bind mount can see it (repo root).
    # Failing anywhere else must not scatter ops/ directories around $HOME.
    if [ -f ./compose.yaml ]; then
        write_state false "$DB_FILE" "$MEDIA_FILE" "$DB_BYTES" "$MEDIA_BYTES" || true
    fi
    rm -f "${TMP_DUMP:-}" "${TMP_MEDIA:-}" 2>/dev/null || true
    exit 1
}

# ── env resolution: explicit environment > .env.local > defaults ─────────────
# PARSE, never source (see header): print the last assignment of $1 from
# ./.env.local without executing a byte of it. The value is captured by the
# caller's command substitution — it is never echoed to the terminal or log.
env_local_value() {
    [ -f ./.env.local ] || return 0
    _v="$(sed -n "s/^[[:space:]]*${1}=//p" ./.env.local | tail -n 1 | tr -d '\r')"
    case "$_v" in # strip one layer of surrounding quotes, compose-style
        \"*\") _v="${_v#\"}"; _v="${_v%\"}" ;;
        \'*\') _v="${_v#\'}"; _v="${_v%\'}" ;;
    esac
    printf '%s' "$_v"
}

[ -n "${CHEFCLAW_BACKUP_DIR-}" ] || CHEFCLAW_BACKUP_DIR="$(env_local_value CHEFCLAW_BACKUP_DIR)"
[ -n "${BACKUP_GPG_PASSPHRASE-}" ] || BACKUP_GPG_PASSPHRASE="$(env_local_value BACKUP_GPG_PASSPHRASE)"
[ -n "${CHEFCLAW_BACKUP_INCLUDE_MEDIA-}" ] || CHEFCLAW_BACKUP_INCLUDE_MEDIA="$(env_local_value CHEFCLAW_BACKUP_INCLUDE_MEDIA)"
[ -n "${DB_USER-}" ] || DB_USER="$(env_local_value DB_USER)"
[ -n "${DB_NAME-}" ] || DB_NAME="$(env_local_value DB_NAME)"

DB_USER="${DB_USER:-chefclaw}"
DB_NAME="${DB_NAME:-chefclaw}"
CHEFCLAW_BACKUP_INCLUDE_MEDIA="${CHEFCLAW_BACKUP_INCLUDE_MEDIA:-1}"

# ── preflight (every refusal names the fix, never a value) ───────────────────
[ -f ./compose.yaml ] || fail "run from the chefclaw repo root (compose.yaml not found here)"
if [ -z "${CHEFCLAW_BACKUP_DIR:-}" ]; then
    fail "CHEFCLAW_BACKUP_DIR is unset — set it in .env.local (or the environment) to the directory encrypted backups should land in"
fi
if [ -z "${BACKUP_GPG_PASSPHRASE:-}" ]; then
    fail "BACKUP_GPG_PASSPHRASE is unset — generate one, store it in the password manager FIRST, then set it in .env.local"
fi
command -v gpg >/dev/null 2>&1 || fail "gpg not found — install it (macOS: brew install gnupg)"
command -v docker >/dev/null 2>&1 || fail "docker not found — is Docker Desktop installed and on PATH?"
mkdir -p "$CHEFCLAW_BACKUP_DIR" || fail "cannot create CHEFCLAW_BACKUP_DIR"

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"

# gpg reads the passphrase on fd 3 (never argv — argv is visible in ps; never
# stdin — stdin carries the plaintext). --pinentry-mode loopback keeps gpg 2.x
# from popping an agent dialog under launchd.
encrypt() {
    # $1 plaintext-in  $2 ciphertext-out. On failure the partial ciphertext is
    # removed — a truncated .gpg left in place would count toward retention and
    # masquerade as a restorable backup.
    gpg --batch --yes --symmetric --cipher-algo AES256 \
        --pinentry-mode loopback --passphrase-fd 3 \
        -o "$2" "$1" 3<<PASSPHRASE_EOF || { rm -f "$2"; return 1; }
${BACKUP_GPG_PASSPHRASE}
PASSPHRASE_EOF
}

file_bytes() {
    # stat -f%z is BSD/macOS; stat -c%s is GNU — try both, fall back to wc.
    stat -f%z "$1" 2>/dev/null || stat -c%s "$1" 2>/dev/null || wc -c <"$1" | tr -d ' '
}

# ── 1. database dump (read-only against the production postgres) ─────────────
DB_FILE="chefclaw-db-${STAMP}.sql.gpg"
TMP_DUMP="${CHEFCLAW_BACKUP_DIR}/.chefclaw-db-${STAMP}.sql.tmp"
log "dumping database '${DB_NAME}' via docker compose exec (read-only) ..."
# Plain-command redirect (no pipeline): the exit status IS pg_dump's — a
# truncated dump can never slip into gpg looking like success.
docker compose exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" >"$TMP_DUMP" \
    || fail "pg_dump failed — is the compose stack up (docker compose ps)?"
[ -s "$TMP_DUMP" ] || fail "pg_dump produced an empty file"
encrypt "$TMP_DUMP" "${CHEFCLAW_BACKUP_DIR}/${DB_FILE}" || fail "gpg encryption of the DB dump failed"
rm -f "$TMP_DUMP"
DB_BYTES="$(file_bytes "${CHEFCLAW_BACKUP_DIR}/${DB_FILE}")"
log "db backup written: ${DB_FILE} (${DB_BYTES} bytes)"

# ── 2. media archive (throwaway :ro container; never touches the stack) ──────
if [ "$CHEFCLAW_BACKUP_INCLUDE_MEDIA" = "1" ]; then
    docker volume inspect "$MEDIA_VOLUME" >/dev/null 2>&1 \
        || fail "media volume ${MEDIA_VOLUME} not found — a bare 'docker run -v' would silently create an empty one and back up nothing"
    MEDIA_FILE="chefclaw-media-${STAMP}.tar.gz.gpg"
    TMP_MEDIA="${CHEFCLAW_BACKUP_DIR}/.chefclaw-media-${STAMP}.tar.gz.tmp"
    log "archiving media volume ${MEDIA_VOLUME} (read-only throwaway container) ..."
    docker run --rm --name "chefclaw-backup-media-${STAMP}" \
        -v "${MEDIA_VOLUME}:/src:ro" alpine \
        tar -czf - -C /src . >"$TMP_MEDIA" \
        || fail "media tar failed"
    encrypt "$TMP_MEDIA" "${CHEFCLAW_BACKUP_DIR}/${MEDIA_FILE}" || fail "gpg encryption of the media archive failed"
    rm -f "$TMP_MEDIA"
    MEDIA_BYTES="$(file_bytes "${CHEFCLAW_BACKUP_DIR}/${MEDIA_FILE}")"
    log "media backup written: ${MEDIA_FILE} (${MEDIA_BYTES} bytes)"
    if [ "$MEDIA_BYTES" -gt "$MEDIA_WARN_BYTES" ]; then
        log "WARNING: media archive exceeds $((MEDIA_WARN_BYTES / 1048576)) MiB — consider CHEFCLAW_BACKUP_INCLUDE_MEDIA=0 or a bigger destination"
    fi
else
    log "media archive skipped (CHEFCLAW_BACKUP_INCLUDE_MEDIA=${CHEFCLAW_BACKUP_INCLUDE_MEDIA})"
fi

# ── 3. prune: keep the newest KEEP_ARTIFACTS of each kind ────────────────────
prune() {
    # $1 glob prefix — names embed a UTC stamp, so lexical sort IS newest-first.
    ls -1 "${CHEFCLAW_BACKUP_DIR}" 2>/dev/null | grep "^${1}" | sort -r \
        | tail -n +"$((KEEP_ARTIFACTS + 1))" \
        | while IFS= read -r _old; do
            log "pruning ${_old}"
            rm -f "${CHEFCLAW_BACKUP_DIR}/${_old}"
        done
}
prune "chefclaw-db-"
prune "chefclaw-media-"

# ── 4. state file for /api/health ────────────────────────────────────────────
write_state true "$DB_FILE" "$MEDIA_FILE" "$DB_BYTES" "$MEDIA_BYTES" \
    || fail "could not write ${STATE_FILE}"
log "backup OK"
