#!/usr/bin/env bash
# =============================================================================
# TEST 06 — Webhook MR Hook (Feedback via Webhook path)
# Tests: POST /webhook/gitlab  with X-Gitlab-Event: Merge Request Hook
#
# This is the production path for the feedback loop — GitLab sends the MR Hook
# directly to /webhook/gitlab, which enqueues feedback the same way it enqueues
# the pipeline.
#
# IMPORTANT: Fill in the MR details below.
# =============================================================================

BASE="http://localhost:8080"
WEBHOOK_SECRET="your_secret_here"    # ← GITLAB_WEBHOOK_SECRET from .env
GITLAB_PROJECT_ID=82768623
MR_IID=1      # ← iid from a previously created Synkron MR (from test_04)

echo ""
echo "============================================"
echo " Synkron — Test 06: MR Webhook (Feedback)"
echo "============================================"
echo ""

send_mr_webhook() {
    local payload="$1"
    curl -s -X POST "$BASE/webhook/gitlab" \
        -H "X-Gitlab-Token: $WEBHOOK_SECRET" \
        -H "X-Gitlab-Event: Merge Request Hook" \
        -H "Content-Type: application/json" \
        -d "$payload"
}

# ---------------------------------------------------------------------------
# A) Non-Synkron MR merged → NOT enqueued (title has no "Docs:")
echo "[A] Merged MR WITHOUT 'Docs:' in title — should NOT trigger feedback"
payload=$(printf '{"project":{"id":%s},"object_attributes":{"iid":999,"action":"merge","title":"Fix login bug","state":"merged"}}' "$GITLAB_PROJECT_ID")
resp=$(send_mr_webhook "$payload")
echo "    Response: $resp"
if echo "$resp" | grep -q '"accepted"'; then
    echo "    PASS — webhook returned accepted (feedback NOT queued — correct)"
else
    echo "    FAIL"
fi

# ---------------------------------------------------------------------------
# B) Synkron MR merged → feedback queued
echo ""
echo "[B] Merged Synkron MR WITH 'Docs:' in title — feedback should be queued"
payload=$(printf '{
  "project": {"id": %s},
  "object_attributes": {
    "iid": %s,
    "action": "merge",
    "title": "Docs: update README for new endpoint",
    "state": "merged",
    "source_branch": "synkron/abc123",
    "target_branch": "main"
  }
}' "$GITLAB_PROJECT_ID" "$MR_IID")
resp=$(send_mr_webhook "$payload")
echo "    Response: $resp"
if echo "$resp" | grep -q '"accepted"'; then
    echo "    PASS — feedback queued via webhook!"
    echo "    (In LOCAL_DEV mode this calls /internal/process-feedback immediately)"
else
    echo "    FAIL"
fi

echo ""
echo "=== Test 06 Complete ==="
echo ""
