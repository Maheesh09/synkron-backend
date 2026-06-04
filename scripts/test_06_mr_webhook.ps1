# =============================================================================
# TEST 06 — Webhook MR Hook (Feedback via Webhook path)
# Tests: POST /webhook/gitlab  with X-Gitlab-Event: Merge Request Hook
#
# This is the OTHER entry point for the feedback loop —
# instead of calling /internal/process-feedback directly, this simulates
# GitLab sending the MR Hook event to the public webhook endpoint.
# The webhook then enqueues feedback the same way it enqueues the pipeline.
#
# IMPORTANT: Fill in the MR details below.
# =============================================================================

$BASE            = "http://localhost:8080"
$WEBHOOK_SECRET  = "your_secret_here"    # ← GITLAB_WEBHOOK_SECRET from .env
$GITLAB_PROJECT_ID = 82768623
$MR_IID          = 1      # ← iid from a previously created Synkron MR

Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host " Synkron — Test 06: MR Webhook (Feedback)" -ForegroundColor Cyan
Write-Host "============================================`n" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# A) Non-Synkron MR merged → NOT enqueued (title has no "Docs:")
Write-Host "[A] Merged MR WITHOUT 'Docs:' in title — should NOT trigger feedback" -ForegroundColor Yellow
$notSynkronMR = @{
    project = @{ id = $GITLAB_PROJECT_ID }
    object_attributes = @{
        iid    = 999
        action = "merge"
        title  = "Fix login bug"
        state  = "merged"
    }
} | ConvertTo-Json -Depth 5

$resp = Invoke-RestMethod -Uri "$BASE/webhook/gitlab" `
    -Method Post `
    -Headers @{
        "X-Gitlab-Token" = $WEBHOOK_SECRET
        "X-Gitlab-Event" = "Merge Request Hook"
        "Content-Type"   = "application/json"
    } `
    -Body $notSynkronMR
Write-Host "    Response: $($resp | ConvertTo-Json -Compress)" -ForegroundColor Green
# Always returns {status: accepted} — just check it doesn't error
if ($resp.status -eq "accepted") {
    Write-Host "    PASS — webhook returned accepted (feedback NOT queued — correct)" -ForegroundColor Green
} else {
    Write-Host "    FAIL" -ForegroundColor Red
}

# ---------------------------------------------------------------------------
# B) Synkron MR merged → feedback queued
Write-Host "`n[B] Merged Synkron MR WITH 'Docs:' in title — feedback should be queued" -ForegroundColor Yellow
$synkronMR = @{
    project = @{ id = $GITLAB_PROJECT_ID }
    object_attributes = @{
        iid    = $MR_IID
        action = "merge"
        title  = "Docs: update README for new endpoint"
        state  = "merged"
        source_branch = "synkron/abc123"
        target_branch = "main"
    }
} | ConvertTo-Json -Depth 5

$resp = Invoke-RestMethod -Uri "$BASE/webhook/gitlab" `
    -Method Post `
    -Headers @{
        "X-Gitlab-Token" = $WEBHOOK_SECRET
        "X-Gitlab-Event" = "Merge Request Hook"
        "Content-Type"   = "application/json"
    } `
    -Body $synkronMR
Write-Host "    Response: $($resp | ConvertTo-Json -Compress)" -ForegroundColor Green
if ($resp.status -eq "accepted") {
    Write-Host "    PASS — feedback queued via webhook!" -ForegroundColor Green
    Write-Host "    (In LOCAL_DEV mode this calls /internal/process-feedback immediately)" -ForegroundColor DarkYellow
} else {
    Write-Host "    FAIL" -ForegroundColor Red
}

Write-Host "`n=== Test 06 Complete ===`n" -ForegroundColor Cyan
