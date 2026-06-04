#!/usr/bin/env bash
# =============================================================================
# TEST 04 — Internal: /internal/run-pipeline
# Directly triggers the full 4-agent documentation pipeline for one commit.
#
# This is the most important test — it exercises:
#   Agent 1: CodeAnalyzer  → reads commit diff from GitLab
#   Agent 2: ImpactMapper  → finds affected docs
#   Agent 3: DocWriter     → rewrites doc sections
#   Agent 4: PRCreator     → opens a merge request
#
# IMPORTANT: Fill in YOUR values before running.
# The commit SHA must exist in the GitLab project.
# =============================================================================

BASE="http://localhost:8080"
INTERNAL_SECRET="synkron-local-dev-secret-change-in-prod"  # INTERNAL_SECRET from .env
GITLAB_PROJECT_ID=82768623                # ← your GitLab project numeric ID
COMMIT_SHA="PASTE_A_REAL_COMMIT_SHA_HERE" # ← full 40-char SHA from your GitLab project

# ---------------------------------------------------------------------------
# Guard: catch unfilled placeholders before hitting the pipeline
if [ "$COMMIT_SHA" = "PASTE_A_REAL_COMMIT_SHA_HERE" ]; then
    echo ""
    echo "  ERROR: You must set a real commit SHA before running this script."
    echo "  1. Open scripts/test_04_pipeline.sh"
    echo "  2. Replace the PASTE_A_REAL_COMMIT_SHA_HERE value on line 18"
    echo "  3. Go to your GitLab project -> Repository -> Commits -> copy any full SHA"
    echo "  Tip: Use a commit that added/changed a feature (not just tests or lock files)"
    echo "       so the pipeline has something doc-worthy to process."
    echo ""
    exit 1
fi

echo ""
echo "========================================"
echo " Synkron — Test 04: Run Full Pipeline"
echo "========================================"
echo ""

# ---------------------------------------------------------------------------
# A) Wrong token → 403
echo "[A] Wrong internal token (expect 403)"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/internal/run-pipeline" \
    -H "X-Internal-Token: WRONG" \
    -H "Content-Type: application/json" \
    -d "{\"after\":\"$COMMIT_SHA\",\"project\":{\"id\":$GITLAB_PROJECT_ID}}")
echo "    HTTP $code"
if [ "$code" = "403" ]; then
    echo "    PASS — got 403 Forbidden"
else
    echo "    FAIL — got $code"
fi

# ---------------------------------------------------------------------------
# B) Missing body → 422
echo ""
echo "[B] Missing body (expect 422 Unprocessable Entity)"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/internal/run-pipeline" \
    -H "X-Internal-Token: $INTERNAL_SECRET" \
    -H "Content-Type: application/json")
echo "    HTTP $code"
if [ "$code" = "422" ]; then
    echo "    PASS — got 422 (body required)"
else
    echo "    FAIL — got $code"
fi

# ---------------------------------------------------------------------------
# C) Full pipeline run
echo ""
echo "[C] Full pipeline run (this may take 30–120 seconds)"
echo "    Project ID : $GITLAB_PROJECT_ID"
echo "    Commit SHA : $COMMIT_SHA"
echo "    Watching server logs is recommended..."
echo ""

body=$(printf '{"after":"%s","project":{"id":%s,"name":"test-project","path_with_namespace":"your-group/test-project"}}' \
    "$COMMIT_SHA" "$GITLAB_PROJECT_ID")

start_time=$(date +%s)
resp=$(curl -s --max-time 300 -X POST "$BASE/internal/run-pipeline" \
    -H "X-Internal-Token: $INTERNAL_SECRET" \
    -H "Content-Type: application/json" \
    -d "$body")
end_time=$(date +%s)
elapsed=$((end_time - start_time))

echo "    Completed in ${elapsed}s"
echo "    Response: $resp"

if echo "$resp" | grep -q '"completed"'; then
    mr_url=$(echo "$resp" | grep -o '"mr_url":"[^"]*"' | cut -d'"' -f4)
    echo "    PASS — pipeline completed!"
    [ -n "$mr_url" ] && echo "    MR URL : $mr_url"
elif echo "$resp" | grep -q '"skipped"'; then
    echo "    INFO — Pipeline skipped (no doc-worthy changes found in this commit)."
    echo "    Try a commit that adds/changes actual feature behaviour."
else
    echo "    FAIL or unexpected result: $resp"
fi

echo ""
echo "=== Test 04 Complete ==="
echo ""
echo "Next: run test_02_dashboard.sh to see this run in /api/runs"
