#!/usr/bin/env bash
# =============================================================================
# TEST 01 — Health & Root Endpoints
# Tests: GET /  and  GET /health
# Expected: Both return 200 with JSON bodies
# =============================================================================

BASE="http://localhost:8080"

echo ""
echo "========================================"
echo " Synkron — Test 01: Health Checks"
echo "========================================"
echo ""

# --- 1. Root ---
echo "[1] GET / (service info)"
resp=$(curl -s "$BASE/")
echo "    Response: $resp"
if echo "$resp" | grep -q '"service":"synkron"'; then
    echo "    PASS"
else
    echo "    FAIL — unexpected body"
fi

# --- 2. Health ---
echo ""
echo "[2] GET /health"
resp=$(curl -s "$BASE/health")
echo "    Response: $resp"
if echo "$resp" | grep -q '"status":"healthy"'; then
    echo "    PASS"
else
    echo "    FAIL — status not 'healthy'"
fi

echo ""
echo "=== Test 01 Complete ==="
echo ""
