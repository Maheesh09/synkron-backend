#!/usr/bin/env bash
# =============================================================================
# TEST 02 — Dashboard Endpoints
# Tests: GET /api/runs   GET /api/health   GET /api/repos
# These are unauthenticated read-only endpoints.
# Expected: 200 with JSON arrays/objects (may be empty on a fresh instance)
# =============================================================================

BASE="http://localhost:8080"

echo ""
echo "========================================"
echo " Synkron — Test 02: Dashboard Endpoints"
echo "========================================"
echo ""

# --- 1. GET /api/runs ---
echo "[1] GET /api/runs"
resp=$(curl -s -w "\n%{http_code}" "$BASE/api/runs")
code=$(echo "$resp" | tail -1)
body=$(echo "$resp" | head -1)
echo "    HTTP $code"
echo "    Response: $body"
if [ "$code" = "200" ]; then
    echo "    PASS"
else
    echo "    FAIL — expected 200"
fi

# --- 2. GET /api/health ---
echo ""
echo "[2] GET /api/health (run statistics)"
resp=$(curl -s -w "\n%{http_code}" "$BASE/api/health")
code=$(echo "$resp" | tail -1)
body=$(echo "$resp" | head -1)
echo "    HTTP $code"
echo "    Response: $body"
if [ "$code" = "200" ] && echo "$body" | grep -q '"total_runs"'; then
    echo "    PASS"
else
    echo "    FAIL — missing total_runs or non-200 status"
fi

# --- 3. GET /api/repos ---
echo ""
echo "[3] GET /api/repos"
resp=$(curl -s -w "\n%{http_code}" "$BASE/api/repos")
code=$(echo "$resp" | tail -1)
body=$(echo "$resp" | head -1)
echo "    HTTP $code"
echo "    Response: $body"
if [ "$code" = "200" ]; then
    echo "    PASS"
else
    echo "    FAIL — expected 200"
fi

echo ""
echo "=== Test 02 Complete ==="
echo ""
