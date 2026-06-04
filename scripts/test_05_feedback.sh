#!/usr/bin/env bash
# =============================================================================
# TEST 05 — Feedback Loop: /internal/process-feedback
# Simulates what happens when a reviewer edits and merges a Synkron MR.
#
# Prerequisites:
#   - At least one pipeline run exists in MongoDB (run test_04 first)
#   - That run must have a docs_updated field and a linked mr_id
#
# IMPORTANT: Fill in the MR iid and project ID from your test run.
# =============================================================================

BASE="http://localhost:8080"
INTERNAL_SECRET="synkron-local-dev-secret-change-in-prod"  # INTERNAL_SECRET from .env
GITLAB_PROJECT_ID=82768623   # ← your GitLab project numeric ID
MR_IID=1                     # ← the iid (not global id) of the Synkron MR from test_04

echo ""
echo "========================================"
echo " Synkron — Test 05: Feedback Loop"
echo "========================================"
echo ""
echo "This test simulates a GitLab 'Merge Request Hook' for a merged Synkron MR."
echo "Synkron will read the final merged content, diff it against what it wrote,"
echo "and store a CorrectionPattern so future runs improve."
echo ""

# ---------------------------------------------------------------------------
# A) Wrong token → 403
echo "[A] Wrong internal token (expect 403)"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/internal/process-feedback" \
    -H "X-Internal-Token: WRONG" \
    -H "Content-Type: application/json" \
    -d '{}')
echo "    HTTP $code"
if [ "$code" = "403" ]; then
    echo "    PASS — got 403"
else
    echo "    FAIL — got $code"
fi

# ---------------------------------------------------------------------------
# B) Simulate a merged Synkron MR event
echo ""
echo "[B] Simulate merged Synkron MR feedback event"
echo "    Project ID : $GITLAB_PROJECT_ID"
echo "    MR iid     : $MR_IID"

payload=$(printf '{
  "project": {"id": %s},
  "object_attributes": {
    "iid": %s,
    "action": "merge",
    "title": "Docs: update README for new endpoint",
    "state": "merged"
  }
}' "$GITLAB_PROJECT_ID" "$MR_IID")

resp=$(curl -s -X POST "$BASE/internal/process-feedback" \
    -H "X-Internal-Token: $INTERNAL_SECRET" \
    -H "Content-Type: application/json" \
    -d "$payload")
echo "    Response: $resp"
if echo "$resp" | grep -q '"processed"'; then
    echo "    PASS — feedback processed. Check MongoDB 'correction_patterns' collection."
else
    echo "    NOTE — no matching pipeline_run found for MR iid=$MR_IID."
    echo "    This is not an error — process_feedback silently returns when no run matches."
    echo "    Make sure the MR iid matches a run created by test_04."
fi

echo ""
echo "=== Test 05 Complete ==="
echo ""
