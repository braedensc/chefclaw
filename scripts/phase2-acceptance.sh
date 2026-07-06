#!/bin/sh
# phase2-acceptance.sh — the Phase-2 golden acceptance run. LOCAL ONLY.
#
# Drives the REAL stack (compose api + worker + sidecar + Gemini) with one
# real video URL: POST /api/recipes/extract, poll the job to a terminal
# state, then sanity-print each stored recipe (dish name, ingredient count,
# first 3 raw_texts — never the whole document).
#
# Kit pattern (docs/LESSONS.md): Claude may INVOKE this script — it resolves
# env at runtime from .env.local, so no secret ever appears in a command line
# or transcript. It must NEVER echo an env value. Exit 0 only on `stored`.
#
# Usage: scripts/phase2-acceptance.sh <video-url> [--wait-seconds N]

set -eu
set +x # defensively: never trace (tracing would echo the token)

usage() {
    echo "usage: $0 <video-url> [--wait-seconds N]" >&2
    exit 2
}

[ "$#" -ge 1 ] || usage
URL=$1
shift
case "$URL" in
http://* | https://*) ;;
*)
    echo "ERROR: first argument must be an http(s) video URL." >&2
    usage
    ;;
esac
WAIT_SECONDS=600
while [ "$#" -gt 0 ]; do
    case "$1" in
    --wait-seconds)
        [ "$#" -ge 2 ] || usage
        WAIT_SECONDS=$2
        shift 2
        ;;
    *) usage ;;
    esac
done

# Run from the repo root (where .env.local lives).
cd "$(dirname "$0")/.."
if [ ! -f .env.local ]; then
    echo "ERROR: .env.local not found in $(pwd) — create it first (human task)." >&2
    exit 1
fi

# Resolve env at runtime; values never printed.
set -a
. ./.env.local
set +a

if [ -z "${CHEFCLAW_API_TOKEN:-}" ]; then
    echo "ERROR: CHEFCLAW_API_TOKEN is not set in .env.local." >&2
    exit 1
fi
API_BASE=${CHEFCLAW_API_BASE:-http://127.0.0.1:8000}

api_curl() {
    # Authorization rides in via a curl config on stdin so the token never
    # appears in any process argv (`ps` would show it on a -H flag). printf
    # is a shell builtin in POSIX sh — the token stays out of argv there too.
    printf 'header = "Authorization: Bearer %s"\n' "$CHEFCLAW_API_TOKEN" |
        curl -sS --config - "$@"
}

json_get() {
    # json_get <json> <field...>  — prints the value at the (nested) field path.
    python3 -c '
import json, sys
value = json.loads(sys.argv[1])
for key in sys.argv[2:]:
    value = value[key]
print(value if value is not None else "")
' "$@"
}

echo "==> POST /api/recipes/extract"
RESPONSE=$(api_curl -X POST "$API_BASE/api/recipes/extract" \
    -H "Content-Type: application/json" \
    --data "$(python3 -c 'import json,sys; print(json.dumps({"url": sys.argv[1]}))' "$URL")")

if ! JOB_ID=$(json_get "$RESPONSE" id 2>/dev/null); then
    echo "ERROR: extract did not return a job resource:" >&2
    echo "$RESPONSE" >&2
    exit 1
fi
echo "    job: $JOB_ID (platform=$(json_get "$RESPONSE" platform) canonical_id=$(json_get "$RESPONSE" canonical_id))"

echo "==> polling GET /api/jobs/$JOB_ID (every 5s, up to ${WAIT_SECONDS}s)"
ELAPSED=0
STATUS=unknown
while [ "$ELAPSED" -le "$WAIT_SECONDS" ]; do
    JOB=$(api_curl "$API_BASE/api/jobs/$JOB_ID")
    STATUS=$(json_get "$JOB" status)
    printf '    [%4ss] status=%s\n' "$ELAPSED" "$STATUS"
    case "$STATUS" in
    stored | failed) break ;;
    esac
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

if [ "$STATUS" != "stored" ]; then
    echo "==> job did NOT store (status=$STATUS)"
    echo "    error_type:   $(json_get "$JOB" error_type)"
    echo "    error_detail: $(json_get "$JOB" error_detail)"
    exit 1
fi

echo "==> job stored — fetching result recipes"
RECIPE_IDS=$(python3 -c '
import json, sys
print("\n".join(json.loads(sys.argv[1])["result_recipe_ids"]))
' "$JOB")

for RECIPE_ID in $RECIPE_IDS; do
    RECIPE=$(api_curl "$API_BASE/api/recipes/$RECIPE_ID")
    python3 -c '
import json, sys
recipe = json.loads(sys.argv[1])
doc = recipe["document"]
name = doc["dish_name"]
ingredients = doc["ingredients"]
print("    recipe " + str(recipe["id"]))
print("      dish_name:   {} / {}".format(name.get("en"), name.get("original")))
print("      ingredients: {}".format(len(ingredients)))
for ingredient in ingredients[:3]:
    print("        - " + ingredient["raw_text"])
' "$RECIPE"
done

echo "==> ACCEPTANCE PASSED (stored)"
exit 0
