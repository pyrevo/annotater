#!/usr/bin/env bash
# In-container integration smoke test for the AnnotateR FastAPI/React image
# (Task 14.6). Run against the production image with the real entrypoint
# available:
#
#   docker run --rm --entrypoint bash annotater:ci /app/scripts/docker_smoke_api.sh
#
# It exercises the *served* application, not the modules: it starts
# start-script.sh exactly as the container does, then drives the HTTP surface
# as two independent browser-like clients (separate cookie jars). Covered:
#
#   1. non-root execution           8. Polars-Bio execution
#   2. healthy startup              9. bundled chromosome normalization
#   3. healthcheck (healthy/unhealthy)
#   4. frontend static serving     10. custom chromosome mapping
#   5. API metadata                11. VCF export
#   6. two independent sessions    12. restart behavior (no session leak)
#   7. upload + temp cleanup       13. temp-storage bounding
#
# Exits non-zero on the first failure.
set -euo pipefail

BASE="http://localhost:8000"
LOG=/tmp/annotater_api_smoke.log
WORK="$(mktemp -d)"
JAR_A="$WORK/a.jar"
JAR_B="$WORK/b.jar"
APP_PID=""

fail() { echo "API SMOKE FAIL: $*" >&2; exit 1; }
ok() { echo "  ok: $*"; }

cleanup() {
    if [ -n "$APP_PID" ]; then kill "$APP_PID" 2>/dev/null || true; fi
    rm -rf "$WORK"
}
trap cleanup EXIT

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
contains() { grep -F -- "$2" <<<"$1" >/dev/null; }
cookie_token() { grep annotater_session "$1" | awk '{print $NF}' | tail -n1; }

wait_health() {
    for _ in $(seq 1 180); do
        if curl -fsS "$BASE/health" >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    return 1
}

start_app() {
    /app/start-script.sh >"$LOG" 2>&1 &
    APP_PID=$!
    wait_health || { cat "$LOG" >&2; fail "app did not become healthy"; }
}

# --- 1. non-root ----------------------------------------------------------
uid="$(id -u)"
[ "$uid" != "0" ] || fail "container is running as root"
ok "non-root: uid=$uid ($(id -un))"

# --- 2. healthy startup + 3. healthcheck ---------------------------------
start_app
HEALTH="$(curl -fsS "$BASE/health")" || fail "/health not reachable"
contains "$HEALTH" '"status":"ok"' || fail "unexpected /health payload: $HEALTH"
ok "healthy startup + /health ok"

# --- 4. frontend static serving ------------------------------------------
[ "$(code "$BASE/")" = "200" ] || fail "frontend index not HTTP 200"
INDEX="$(curl -fsS "$BASE/")"
contains "$INDEX" 'id="root"' || fail "frontend index missing React root element"
asset="$(grep -o '/assets/[^"]*\.js' <<<"$INDEX" | head -n1 || true)"
[ -n "$asset" ] || fail "frontend index references no JS asset"
[ "$(code "$BASE$asset")" = "200" ] || fail "frontend asset $asset not HTTP 200"
ok "frontend static serving ok ($asset)"

# --- 5. API metadata ------------------------------------------------------
META="$(curl -fsS "$BASE/api/meta")" || fail "/api/meta not reachable"
contains "$META" 'AnnotateR' || fail "/api/meta missing application name"
contains "$META" 'bedtools' || fail "/api/meta missing engine list"
ok "/api/meta ok"

# --- 6. two independent sessions -----------------------------------------
# Stateless reads (no cookie) are served by throwaway sessions: they return
# 404 and are issued NO cookie, so anonymous traffic cannot consume session
# capacity (review finding F7). Only state-changing requests create a session.
curl -fsS -c "$JAR_A" -b "$JAR_A" -X POST "$BASE/api/load-sample" \
    -d 'sample_id=gene_overlap' -o /dev/null || fail "session A load-sample failed"
TOKEN_A="$(cookie_token "$JAR_A")"
[ -n "$TOKEN_A" ] || fail "session A received no session cookie"

[ "$(code -c "$JAR_B" -b "$JAR_B" "$BASE/api/results/data")" = "404" ] \
    || fail "session B unexpectedly saw results before doing anything"
[ -z "$(cookie_token "$JAR_B" || true)" ] \
    || fail "stateless read was issued a session cookie"

curl -fsS -c "$JAR_B" -b "$JAR_B" -X POST "$BASE/api/load-sample" \
    -d 'sample_id=gene_overlap' -o /dev/null || fail "session B load-sample failed"
TOKEN_B="$(cookie_token "$JAR_B")"
[ -n "$TOKEN_B" ] || fail "session B received no session cookie after a write"
[ "$TOKEN_A" != "$TOKEN_B" ] || fail "two clients were issued the same session token"
ok "two independent sessions (distinct tokens; stateless reads cookie-free)"

# --- 7. Bedtools execution + session isolation ---------------------------
EXEC_BEDTOOLS='{"engine":"bedtools","mode":"overlap","join":"left","feature_types":["gene"]}'
RESP_A="$(curl -fsS -c "$JAR_A" -b "$JAR_A" -H 'Content-Type: application/json' \
    -d "$EXEC_BEDTOOLS" "$BASE/api/execute")" || fail "bedtools execute request failed"
contains "$RESP_A" '"status":"success"' || fail "bedtools execute not successful: $RESP_A"
contains "$RESP_A" '"result_count":6' || fail "bedtools execute returned unexpected row count"

[ "$(code -c "$JAR_B" -b "$JAR_B" "$BASE/api/results/data")" = "404" ] \
    || fail "session B saw session A's results (isolation breach)"
[ "$(code -c "$JAR_A" -b "$JAR_A" "$BASE/api/results/data")" = "200" ] \
    || fail "session A lost its own results"
ok "Bedtools execution + per-session isolation ok"

# --- 8. Polars-Bio execution ---------------------------------------------
RESP_PB="$(curl -fsS -c "$JAR_A" -b "$JAR_A" -H 'Content-Type: application/json' \
    -d '{"engine":"polars-bio","mode":"overlap"}' "$BASE/api/execute")" \
    || fail "polars-bio execute request failed"
contains "$RESP_PB" '"status":"success"' || fail "polars-bio execute not successful"
contains "$RESP_PB" '"result_count":6' || fail "polars-bio execute returned unexpected row count"
ok "Polars-Bio execution ok"

# --- 9. bundled chromosome normalization ---------------------------------
RESP_NORM="$(curl -fsS -c "$JAR_A" -b "$JAR_A" -H 'Content-Type: application/json' \
    -d '{"engine":"bedtools","mode":"overlap","assembly":"GRCh38","chr_naming":"ensembl"}' "$BASE/api/execute")" \
    || fail "chromosome-normalization execute failed"
contains "$RESP_NORM" '"chromosome_normalization":{' \
    || fail "expected a non-null chromosome_normalization report"
ok "bundled chromosome normalization ok"

# --- 7b. upload + temp cleanup -------------------------------------------
before="$(find /tmp -maxdepth 1 -name 'annotater-upload-*' | wc -l | tr -d ' ')"
printf 'chr1\t10\t20\nchr1\t30\t40\n' >"$WORK/q.bed"
curl -fsS -c "$JAR_B" -b "$JAR_B" -F "file=@$WORK/q.bed" -F "role=query" \
    "$BASE/api/upload" -o /dev/null || fail "upload failed"
after="$(find /tmp -maxdepth 1 -name 'annotater-upload-*' | wc -l | tr -d ' ')"
[ "$before" = "$after" ] || fail "upload left a temporary directory behind ($before -> $after)"
[ "$after" = "0" ] || fail "temporary upload directories are piling up ($after)"
ok "upload + temporary-storage cleanup ok"

# --- 10. custom chromosome mapping ---------------------------------------
printf 'seq,begin,finish\nchr1,10,20\nchr1,30,40\n' >"$WORK/custom.csv"
curl -fsS -c "$JAR_B" -b "$JAR_B" -F "file=@$WORK/custom.csv" -F "role=query" \
    "$BASE/api/upload" -o /dev/null || fail "custom upload failed"
RESP_MAP="$(curl -fsS -c "$JAR_B" -b "$JAR_B" -H 'Content-Type: application/json' \
    -d '{"chr_col":"seq","start_col":"begin","end_col":"finish","coord_system":"0-based"}' \
    "$BASE/api/apply-mapping")" || fail "apply-mapping request failed"
contains "$RESP_MAP" '"status":"success"' || fail "apply-mapping not successful: $RESP_MAP"
ok "custom chromosome mapping ok"

# --- 11. VCF export -------------------------------------------------------
curl -fsS -c "$JAR_A" -b "$JAR_A" -X POST "$BASE/api/load-sample" \
    -d 'sample_id=closest_variants' -o /dev/null || fail "VCF sample load failed"
curl -fsS -c "$JAR_A" -b "$JAR_A" -H 'Content-Type: application/json' \
    -d '{"engine":"bedtools","mode":"overlap"}' "$BASE/api/execute" -o /dev/null \
    || fail "execute for VCF export failed"
curl -fsS -c "$JAR_A" -b "$JAR_A" "$BASE/api/export/vcf" -o "$WORK/out.vcf" \
    || fail "VCF export request failed"
head -n1 "$WORK/out.vcf" | grep -q '^##fileformat=VCF' || fail "VCF export is not a VCF"
grep -q '^#CHROM' "$WORK/out.vcf" || fail "VCF export has no column header line"
ok "VCF export ok"

# --- 3b/12. unhealthy + restart behavior ---------------------------------
kill "$APP_PID" 2>/dev/null || true
wait "$APP_PID" 2>/dev/null || true
APP_PID=""
sleep 1
if curl -fsS "$BASE/health" >/dev/null 2>&1; then
    fail "health probe succeeded while the app was down"
fi
ok "unhealthy behavior: /health fails when the app is stopped"

start_app
[ "$(code -b "$JAR_A" "$BASE/api/results/data")" = "404" ] \
    || fail "restart leaked or reassigned session state"
ok "restart resets session state (no leak)"

echo "API SMOKE PASS"
