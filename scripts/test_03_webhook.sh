#!/usr/bin/env bash
# =============================================================================
# TEST 03 — Webhook Endpoint (GitLab Push Event Simulation)
# Tests: POST /webhook/gitlab
#
# Covers:
#   A) Rejected without secret                  → 401
#   B) Empty push (branch delete)               → ignored
#   C) Bot commit (synkron-bot user)            → ignored (loop guard)
#   D) Real push with commits                   → accepted + queued
#
# IMPORTANT: Fill in YOUR values below before running.
# =============================================================================

BASE="http://localhost:8080"
WEBHOOK_SECRET="your_secret_here"    # ← must match GITLAB_WEBHOOK_SECRET in .env
GITLAB_PROJECT_ID=82768623           # ← your GitLab project numeric ID
REAL_COMMIT_SHA="PASTE_A_REAL_COMMIT_SHA_HERE"  # ← any valid commit SHA from your GitLab project

# ---------------------------------------------------------------------------
# Guard: catch unfilled placeholders before any network call
if [ "$REAL_COMMIT_SHA" = "PASTE_A_REAL_COMMIT_SHA_HERE" ]; then
    echo ""
    echo "  ERROR: You must set a real commit SHA before running this script."
    echo "  1. Open scripts/test_03_webhook.sh"
    echo "  2. Replace the PASTE_A_REAL_COMMIT_SHA_HERE value on line 17"
    echo "  3. Go to your GitLab project -> Repository -> Commits -> copy any full SHA"
    echo ""
    exit 1
fi
if [ "$WEBHOOK_SECRET" = "your_secret_here" ]; then
    echo ""
    echo "  ERROR: Set WEBHOOK_SECRET to match GITLAB_WEBHOOK_SECRET in your .env file."
    echo ""
    exit 1
fi

echo ""
echo "========================================"
echo " Synkron — Test 03: Webhook (Push)"
echo "========================================"
echo ""

# Helper: send a webhook event and return body
send_webhook() {
    local payload="$1"
    local secret="$2"
    local event="${3:-Push Hook}"
    curl -s -X POST "$BASE/webhook/gitlab" \
        -H "X-Gitlab-Token: $secret" \
        -H "X-Gitlab-Event: $event" \
        -H "Content-Type: application/json" \
        -d "$payload"
}

# ---------------------------------------------------------------------------
# A) No secret → 401
echo "[A] Webhook with WRONG secret (expect 401)"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/webhook/gitlab" \
    -H "X-Gitlab-Token: WRONG_SECRET" \
    -H "X-Gitlab-Event: Push Hook" \
    -H "Content-Type: application/json" \
    -d '{"total_commits_count":1}')
echo "    HTTP $code"
if [ "$code" = "401" ]; then
    echo "    PASS — got 401 Unauthorized"
else
    echo "    FAIL — got $code instead of 401"
fi

# ---------------------------------------------------------------------------
# B) Empty push (0 commits) → ignored
echo ""
echo "[B] Empty push / branch delete (expect ignored)"
payload=$(printf '{"total_commits_count":0,"project":{"id":%s},"user_username":"someone"}' "$GITLAB_PROJECT_ID")
resp=$(send_webhook "$payload" "$WEBHOOK_SECRET")
echo "    Response: $resp"
if echo "$resp" | grep -q '"no commits"'; then
    echo "    PASS"
else
    echo "    FAIL — expected {status:ignored, reason:no commits}"
fi

# ---------------------------------------------------------------------------
# C) Bot commit → ignored (prevents infinite loop)
echo ""
echo "[C] Push from synkron-bot (loop guard, expect ignored)"
payload=$(printf '{"total_commits_count":1,"user_username":"synkron-bot","project":{"id":%s},"after":"%s","commits":[{"id":"%s","message":"Docs: update README"}]}' \
    "$GITLAB_PROJECT_ID" "$REAL_COMMIT_SHA" "$REAL_COMMIT_SHA")
resp=$(send_webhook "$payload" "$WEBHOOK_SECRET")
echo "    Response: $resp"
if echo "$resp" | grep -q '"synkron commit"'; then
    echo "    PASS"
else
    echo "    FAIL — expected {status:ignored, reason:synkron commit}"
fi

# ---------------------------------------------------------------------------
# D) Real developer push → accepted (pipeline queued)
echo ""
echo "[D] Real developer push (expect accepted + pipeline queued)"
echo "    NOTE: This queues a full pipeline run. Watch the server logs!"
payload=$(printf '{
  "total_commits_count": 1,
  "user_username": "developer",
  "project": {"id": %s, "name": "test-project", "path_with_namespace": "your-group/test-project"},
  "after": "%s",
  "commits": [{"id": "%s", "message": "feat: add new endpoint for user profile", "author": {"name": "Developer", "email": "dev@example.com"}}],
  "ref": "refs/heads/main"
}' "$GITLAB_PROJECT_ID" "$REAL_COMMIT_SHA" "$REAL_COMMIT_SHA")
resp=$(send_webhook "$payload" "$WEBHOOK_SECRET")
echo "    Response: $resp"
if echo "$resp" | grep -q '"accepted"'; then
    echo "    PASS — webhook accepted. Check server logs for pipeline progress."
else
    echo "    FAIL — unexpected response"
fi

echo ""
echo "=== Test 03 Complete ==="
echo ""
echo "Tip: Run test_02_dashboard.sh again to see the new pipeline run in /api/runs"
