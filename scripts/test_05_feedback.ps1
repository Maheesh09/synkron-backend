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

$BASE            = "http://localhost:8080"
$INTERNAL_SECRET = "synkron-local-dev-secret-change-in-prod"  # INTERNAL_SECRET from .env
$GITLAB_PROJECT_ID = 82768623   # ← your GitLab project numeric ID
$MR_IID          = 1            # ← the iid (not global id) of the Synkron MR from test_04

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " Synkron — Test 05: Feedback Loop" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

Write-Host "This test simulates a GitLab 'Merge Request Hook' for a merged Synkron MR." -ForegroundColor DarkGray
Write-Host "Synkron will read the final merged content, diff it against what it wrote," -ForegroundColor DarkGray
Write-Host "and store a CorrectionPattern so future runs improve.`n" -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
# A) Wrong token → 403
Write-Host "[A] Wrong internal token (expect 403)" -ForegroundColor Yellow
try {
    Invoke-RestMethod -Uri "$BASE/internal/process-feedback" `
        -Method Post `
        -Headers @{ "X-Internal-Token" = "WRONG"; "Content-Type" = "application/json" } `
        -Body (@{} | ConvertTo-Json)
    Write-Host "    FAIL — should have returned 403" -ForegroundColor Red
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 403) {
        Write-Host "    PASS — got 403" -ForegroundColor Green
    } else {
        Write-Host "    FAIL — got $code" -ForegroundColor Red
    }
}

# ---------------------------------------------------------------------------
# B) Simulate a merged Synkron MR event
Write-Host "`n[B] Simulate merged Synkron MR feedback event" -ForegroundColor Yellow
Write-Host "    Project ID : $GITLAB_PROJECT_ID" -ForegroundColor DarkGray
Write-Host "    MR iid     : $MR_IID" -ForegroundColor DarkGray

# This mirrors the shape GitLab sends on a Merge Request Hook with action=merge
$feedbackPayload = @{
    project = @{ id = $GITLAB_PROJECT_ID }
    object_attributes = @{
        iid    = $MR_IID
        action = "merge"
        title  = "Docs: update README for new endpoint"
        state  = "merged"
    }
} | ConvertTo-Json -Depth 5

try {
    $result = Invoke-RestMethod -Uri "$BASE/internal/process-feedback" `
                -Method Post `
                -Headers @{
                    "X-Internal-Token" = $INTERNAL_SECRET
                    "Content-Type"     = "application/json"
                } `
                -Body $feedbackPayload

    Write-Host "    Response: $($result | ConvertTo-Json -Compress)" -ForegroundColor Green
    if ($result.status -eq "processed") {
        Write-Host "    PASS — feedback processed. Check MongoDB 'correction_patterns' collection." -ForegroundColor Green
    } else {
        Write-Host "    FAIL — unexpected status" -ForegroundColor Red
    }
} catch {
    Write-Host "    FAIL — $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "    Tip: This test only stores data if the MR iid matches a pipeline_run in MongoDB." -ForegroundColor DarkYellow
    Write-Host "         If no run is found, process_feedback silently returns — that is not a bug." -ForegroundColor DarkYellow
}

Write-Host "`n=== Test 05 Complete ===`n" -ForegroundColor Cyan
