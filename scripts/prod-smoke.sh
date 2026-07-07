#!/bin/sh
# prod-smoke.sh — post-deploy smoke test for a deployed chefclaw instance.
# Works for BOTH deploy postures: the M4 public-TLS ingress (a reverse proxy —
# Caddy — terminating HTTPS in front of 127.0.0.1:8000, https://<domain>) and
# the interim Tailscale-private path (tailscale serve, https://<host>.<tailnet>
# .ts.net). Run it from a client that can reach the URL (your Mac) right after
# `docker compose up`.
#
# Verifies the four things the deploy acceptance calls for:
#   1. reachability     — the SPA index answers 200 over the deploy URL
#   2. auth is enforced — /api/health is 401 WITHOUT a session (HARD), and 200
#                         WITH a session cookie when you supply one (see below)
#   3. health is green  — db ok + worker alive (warns on stale backup / sidecar
#                         unreachable / fail-closed budget / Sentry off)
#   4. no public ports  — 8000 and 5432 are NOT reachable on the public IP
#                         (they stay 127.0.0.1-bound; only 80/443 via the proxy,
#                         or the tailnet, are meant to be ingress)
#
# AUTH NOTE (post-M2): auth is Google OAuth + an opaque `chefclaw_session`
# cookie — the old bearer token no longer gates requests. A session cookie
# can't be minted headlessly (OAuth needs a browser), so the authenticated
# 200 leg is OPTIONAL: sign in once in a browser, copy the `chefclaw_session`
# cookie value (DevTools → Application → Cookies), and pass it as the
# CHEFCLAW_SESSION env var. Without it, the script still runs every headless
# check (SPA 200, the 401-without-session assertion, and the public-port scan)
# and just WARNs that it skipped the authenticated leg. CHEFCLAW_SESSION is
# read from the environment, NEVER an argument (args leak via `ps`/history),
# and is never echoed (Hard Rule 2: secrets are referenced by name only).
#
# Usage:
#   sh scripts/prod-smoke.sh https://<domain> [PUBLIC_IP]                       # headless checks
#   CHEFCLAW_SESSION=... sh scripts/prod-smoke.sh https://<domain> [PUBLIC_IP]  # + authed leg
#
# Exit status is non-zero if any HARD check fails (unreachable, auth not
# enforced, or — when a session is supplied — db down / worker dead / a public
# port open). A stale backup, unreachable sidecar, unconfigured budget, or
# Sentry-off is a WARNING only — the deploy is usable, but the posture is
# flagged.

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

# 1. Reachability — the SPA index responds over the deploy URL. `-w
#    '%{http_code}'` prints no trailing newline, so a `|| echo 000` fallback
#    would concatenate into "000000" and slip past the 000 case; use `|| code=000`
#    which REPLACES the value (curl already prints 000 on a connect failure).
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/" 2>/dev/null) || code=000
case "$code" in
0 | 000) bad "unreachable — no response from $BASE_URL (proxy/tailnet down? wrong URL?)" ;;
200) ok "reachable — SPA index returned 200 ($BASE_URL)" ;;
*) warn "SPA index returned $code (expected 200)" ;;
esac

# 2a. Auth is enforced — /api/health MUST 401 without a session (it exposes
#     spend/cookie/backup state; it is deliberately NOT publicly exempt). This
#     is the load-bearing security assertion and is fully headless.
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/api/health" 2>/dev/null) || code=000
if [ "$code" = "401" ]; then
	ok "auth enforced — /api/health is 401 without a session"
else
	bad "auth NOT enforced — /api/health returned $code without a session (expected 401)"
fi

# 2b. With a valid session cookie it MUST 200. OPTIONAL: a session can't be
#     minted headlessly (OAuth needs a browser), so this leg runs only when you
#     supply CHEFCLAW_SESSION (sign in, copy the `chefclaw_session` cookie). One
#     request; split body from the trailing status code. Cookie via env only;
#     never echoed.
health_json=""
if [ -z "${CHEFCLAW_SESSION:-}" ]; then
	warn "CHEFCLAW_SESSION not set — skipping the authenticated 200 leg. Headless"
	warn "  checks still ran; to include it, sign in, copy the chefclaw_session"
	warn "  cookie, and re-run with CHEFCLAW_SESSION=... set."
else
	resp=$(curl -sS --max-time 10 -H "Cookie: chefclaw_session=${CHEFCLAW_SESSION}" \
		-w '\n%{http_code}' "$BASE_URL/api/health" 2>/dev/null || printf '\n000')
	code=$(printf '%s' "$resp" | tail -n1)
	health_json=$(printf '%s' "$resp" | sed '$d')
	if [ "$code" = "200" ]; then
		ok "authenticated — /api/health is 200 with the session cookie"
	else
		bad "authenticated request returned $code (expected 200 — is the session still valid?)"
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
