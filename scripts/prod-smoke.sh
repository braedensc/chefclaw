#!/bin/sh
# prod-smoke.sh — post-deploy smoke test for a deployed chefclaw instance
# (V2-B deploy acceptance + V2-D's "repeatable prod-smoke check"). Run it from
# a tailnet-connected client (e.g. your Mac) right after `docker compose up`.
#
# Verifies the four things the deploy acceptance calls for:
#   1. reachability     — the SPA + API answer over the tailnet URL
#   2. auth is enforced — /api/health is 401 without a token, 200 with it
#   3. health is green  — db ok + worker alive (warns on stale backup / sidecar
#                         unreachable / fail-closed budget / Sentry off)
#   4. no public ports  — 8000 and 5432 are NOT reachable on the public IP
#                         (they must be 127.0.0.1-bound; tailscale serve is the
#                         only ingress)
#
# The token is read from the environment (CHEFCLAW_API_TOKEN), NEVER passed as
# an argument — arguments show up in `ps` and shell history. It is never echoed
# (Hard Rule 2: secrets are referenced by name only).
#
# Usage:
#   CHEFCLAW_API_TOKEN=... sh scripts/prod-smoke.sh https://<host>.<tailnet>.ts.net [PUBLIC_IP]
#
# Exit status is non-zero if any HARD check fails (unreachable, auth not
# enforced, db down, worker dead, or a public port open). A stale backup,
# unreachable sidecar, unconfigured budget, or Sentry-off is a WARNING only —
# the deploy is usable, but the posture is flagged.

set -eu

BASE_URL="${1:-}"
PUBLIC_IP="${2:-}"

if [ -z "$BASE_URL" ]; then
	echo "usage: CHEFCLAW_API_TOKEN=... sh scripts/prod-smoke.sh <base-url> [public-ip]" >&2
	exit 2
fi
BASE_URL="${BASE_URL%/}" # strip a trailing slash

fail=0
ok() { printf 'OK    %s\n' "$1"; }
warn() { printf 'WARN  %s\n' "$1"; }
bad() {
	printf 'FAIL  %s\n' "$1"
	fail=1
}

# 1. Reachability — the SPA index responds over the tailnet URL.
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/" 2>/dev/null || echo 000)
case "$code" in
0 | 000) bad "unreachable — no response from $BASE_URL (tailnet down? wrong URL?)" ;;
200) ok "reachable — SPA index returned 200 ($BASE_URL)" ;;
*) warn "SPA index returned $code (expected 200)" ;;
esac

# 2a. Auth is enforced — /api/health MUST 401 without a token (it exposes
#     spend/cookie state; it is deliberately NOT publicly exempt).
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/api/health" 2>/dev/null || echo 000)
if [ "$code" = "401" ]; then
	ok "auth enforced — /api/health is 401 without a token"
else
	bad "auth NOT enforced — /api/health returned $code without a token (expected 401)"
fi

# 2b. With the token it MUST 200. One request; split body from the trailing
#     status code. Token via env only; never echoed.
health_json=""
if [ -z "${CHEFCLAW_API_TOKEN:-}" ]; then
	bad "CHEFCLAW_API_TOKEN is not set — cannot test the authenticated path"
else
	resp=$(curl -sS --max-time 10 -H "Authorization: Bearer ${CHEFCLAW_API_TOKEN}" \
		-w '\n%{http_code}' "$BASE_URL/api/health" 2>/dev/null || printf '\n000')
	code=$(printf '%s' "$resp" | tail -n1)
	health_json=$(printf '%s' "$resp" | sed '$d')
	if [ "$code" = "200" ]; then
		ok "authenticated — /api/health is 200 with the token"
	else
		bad "authenticated request returned $code (expected 200 — is the token right?)"
		health_json=""
	fi
fi

# 3. Health is green — parse the JSON (python3 ships on the client + any VPS).
if [ -n "$health_json" ] && command -v python3 >/dev/null 2>&1; then
	python3 - "$health_json" <<'PY' || fail=1
import json, sys
try:
    h = json.loads(sys.argv[1])
except Exception:
    print("FAIL  /api/health did not return JSON")
    sys.exit(1)
rc = 0
if h.get("db") == "ok":
    print("OK    db=ok")
else:
    print(f"FAIL  db={h.get('db')}"); rc = 1
if h.get("worker") == "alive":
    print("OK    worker=alive")
else:
    print(f"FAIL  worker={h.get('worker')} (the extraction worker is not running)"); rc = 1
# Non-fatal posture warnings — the deploy works, but flag them.
if h.get("backup") == "stale":
    print("WARN  backup=stale — check the systemd timer")
elif h.get("backup") == "not_configured":
    print("WARN  backup=not_configured — schedule the backup timer")
if h.get("sidecar") == "unreachable":
    print("WARN  sidecar=unreachable — Rednote fetch is down")
if h.get("budget_monthly_usd") is None:
    print("WARN  budget not configured — extraction is fail-closed (no paid calls)")
if not h.get("sentry_enabled"):
    print("WARN  Sentry not enabled (SENTRY_DSN unset) — errors go to logs only")
sys.exit(rc)
PY
elif [ -n "$health_json" ]; then
	warn "python3 not found — skipping the health-field checks (raw body fetched OK)"
fi

# 4. No public ports — 8000/5432 must NOT be reachable on the public IP. Run
#    this from OFF the box (a from-the-internet check), so pass the public IP.
if [ -n "$PUBLIC_IP" ]; then
	if command -v nc >/dev/null 2>&1; then
		for port in 8000 5432; do
			if nc -z -w 3 "$PUBLIC_IP" "$port" 2>/dev/null; then
				bad "port $port is OPEN on public IP $PUBLIC_IP — must be 127.0.0.1-bound only!"
			else
				ok "port $port is closed on the public IP (good)"
			fi
		done
	else
		warn "nc not found — cannot scan public ports; verify manually (nmap $PUBLIC_IP)"
	fi
else
	warn "no public IP given — skipping the public-port scan (pass it as arg 2 to verify)"
fi

echo
if [ "$fail" -eq 0 ]; then
	echo "prod-smoke: PASS"
else
	echo "prod-smoke: FAIL (see above)"
fi
exit "$fail"
