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

$BASE            = "http://localhost:8080"
$WEBHOOK_SECRET  = "your_secret_here"   # ← must match GITLAB_WEBHOOK_SECRET in .env
$GITLAB_PROJECT_ID = 82768623           # ← your GitLab project numeric ID
$REAL_COMMIT_SHA   = "PASTE_A_REAL_COMMIT_SHA_HERE"  # ← any valid commit SHA

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " Synkron — Test 03: Webhook (Push)" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# Helper: send a webhook event
function Send-Webhook($payload, $secret, $event = "Push Hook") {
    $headers = @{
        "X-Gitlab-Token" = $secret
        "X-Gitlab-Event" = $event
        "Content-Type"   = "application/json"
    }
    try {
        $resp = Invoke-RestMethod -Uri "$BASE/webhook/gitlab" `
                    -Method Post `
                    -Headers $headers `
                    -Body ($payload | ConvertTo-Json -Depth 10)
        return $resp
    } catch {
        return $_.Exception.Response
    }
}

# ---------------------------------------------------------------------------
# A) No secret → 401
Write-Host "[A] Webhook with WRONG secret (expect 401)" -ForegroundColor Yellow
try {
    $badHeaders = @{
        "X-Gitlab-Token" = "WRONG_SECRET"
        "X-Gitlab-Event" = "Push Hook"
        "Content-Type"   = "application/json"
    }
    Invoke-RestMethod -Uri "$BASE/webhook/gitlab" `
        -Method Post -Headers $badHeaders `
        -Body (@{total_commits_count=1} | ConvertTo-Json)
    Write-Host "    FAIL — should have returned 401" -ForegroundColor Red
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 401) {
        Write-Host "    PASS — got 401 Unauthorized" -ForegroundColor Green
    } else {
        Write-Host "    FAIL — got $code instead of 401" -ForegroundColor Red
    }
}

# ---------------------------------------------------------------------------
# B) Empty push (0 commits) → ignored
Write-Host "`n[B] Empty push / branch delete (expect ignored)" -ForegroundColor Yellow
$emptyPush = @{
    total_commits_count = 0
    project = @{ id = $GITLAB_PROJECT_ID }
    user_username = "someone"
}
$r = Send-Webhook $emptyPush $WEBHOOK_SECRET
Write-Host "    Response: $($r | ConvertTo-Json -Compress)" -ForegroundColor Green
if ($r.status -eq "ignored" -and $r.reason -eq "no commits") {
    Write-Host "    PASS" -ForegroundColor Green
} else {
    Write-Host "    FAIL — expected {status:ignored, reason:no commits}" -ForegroundColor Red
}

# ---------------------------------------------------------------------------
# C) Bot commit → ignored (prevents infinite loop)
Write-Host "`n[C] Push from synkron-bot (loop guard, expect ignored)" -ForegroundColor Yellow
$botPush = @{
    total_commits_count = 1
    user_username = "synkron-bot"
    project = @{ id = $GITLAB_PROJECT_ID }
    after = $REAL_COMMIT_SHA
    commits = @(@{ id = $REAL_COMMIT_SHA; message = "Docs: update README" })
}
$r = Send-Webhook $botPush $WEBHOOK_SECRET
Write-Host "    Response: $($r | ConvertTo-Json -Compress)" -ForegroundColor Green
if ($r.status -eq "ignored" -and $r.reason -eq "synkron commit") {
    Write-Host "    PASS" -ForegroundColor Green
} else {
    Write-Host "    FAIL — expected {status:ignored, reason:synkron commit}" -ForegroundColor Red
}

# ---------------------------------------------------------------------------
# D) Real developer push → accepted (pipeline queued)
Write-Host "`n[D] Real developer push (expect accepted + pipeline queued)" -ForegroundColor Yellow
Write-Host "    NOTE: This queues a full pipeline run. Watch the server logs!" -ForegroundColor DarkYellow
$realPush = @{
    total_commits_count = 1
    user_username = "developer"
    project = @{
        id                  = $GITLAB_PROJECT_ID
        name                = "test-project"
        path_with_namespace = "your-group/test-project"
    }
    after = $REAL_COMMIT_SHA
    commits = @(
        @{
            id      = $REAL_COMMIT_SHA
            message = "feat: add new endpoint for user profile"
            author  = @{ name = "Developer"; email = "dev@example.com" }
        }
    )
    ref = "refs/heads/main"
}
$r = Send-Webhook $realPush $WEBHOOK_SECRET
Write-Host "    Response: $($r | ConvertTo-Json -Compress)" -ForegroundColor Green
if ($r.status -eq "accepted") {
    Write-Host "    PASS — webhook accepted. Check server logs for pipeline progress." -ForegroundColor Green
} else {
    Write-Host "    FAIL — unexpected response" -ForegroundColor Red
}

Write-Host "`n=== Test 03 Complete ===`n" -ForegroundColor Cyan
Write-Host "Tip: Run 'test_02_dashboard.ps1' again to see the new pipeline run in /api/runs" -ForegroundColor DarkYellow
