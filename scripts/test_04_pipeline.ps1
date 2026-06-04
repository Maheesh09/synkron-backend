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

$BASE            = "http://localhost:8080"
$INTERNAL_SECRET = "synkron-local-dev-secret-change-in-prod"  # INTERNAL_SECRET from .env
$GITLAB_PROJECT_ID = 82768623                # ← your GitLab project numeric ID
$COMMIT_SHA        = "PASTE_A_REAL_COMMIT_SHA_HERE"  # ← full 40-char SHA

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " Synkron — Test 04: Run Full Pipeline" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# A) Wrong token → 403
Write-Host "[A] Wrong internal token (expect 403)" -ForegroundColor Yellow
try {
    Invoke-RestMethod -Uri "$BASE/internal/run-pipeline" `
        -Method Post `
        -Headers @{ "X-Internal-Token" = "WRONG"; "Content-Type" = "application/json" } `
        -Body (@{ after = $COMMIT_SHA; project = @{ id = $GITLAB_PROJECT_ID } } | ConvertTo-Json)
    Write-Host "    FAIL — should have returned 403" -ForegroundColor Red
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 403) {
        Write-Host "    PASS — got 403 Forbidden" -ForegroundColor Green
    } else {
        Write-Host "    FAIL — got $code" -ForegroundColor Red
    }
}

# ---------------------------------------------------------------------------
# B) Missing body → 422
Write-Host "`n[B] Missing body (expect 422 Unprocessable Entity)" -ForegroundColor Yellow
try {
    Invoke-RestMethod -Uri "$BASE/internal/run-pipeline" `
        -Method Post `
        -Headers @{ "X-Internal-Token" = $INTERNAL_SECRET; "Content-Type" = "application/json" }
    Write-Host "    FAIL — should have returned 422" -ForegroundColor Red
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 422) {
        Write-Host "    PASS — got 422 (body required)" -ForegroundColor Green
    } else {
        Write-Host "    FAIL — got $code" -ForegroundColor Red
    }
}

# ---------------------------------------------------------------------------
# C) Full pipeline run
Write-Host "`n[C] Full pipeline run (this may take 30–120 seconds)" -ForegroundColor Yellow
Write-Host "    Project ID : $GITLAB_PROJECT_ID" -ForegroundColor DarkGray
Write-Host "    Commit SHA : $COMMIT_SHA" -ForegroundColor DarkGray
Write-Host "    Watching server logs is recommended...`n" -ForegroundColor DarkYellow

$body = @{
    after   = $COMMIT_SHA
    project = @{
        id                  = $GITLAB_PROJECT_ID
        name                = "test-project"
        path_with_namespace = "your-group/test-project"
    }
} | ConvertTo-Json

$start = Get-Date
try {
    $result = Invoke-RestMethod -Uri "$BASE/internal/run-pipeline" `
                -Method Post `
                -Headers @{
                    "X-Internal-Token" = $INTERNAL_SECRET
                    "Content-Type"     = "application/json"
                } `
                -Body $body `
                -TimeoutSec 300   # agents can take a while

    $elapsed = ((Get-Date) - $start).TotalSeconds
    Write-Host "    Completed in $([math]::Round($elapsed,1))s" -ForegroundColor Green
    Write-Host "    Status : $($result.status)" -ForegroundColor Green

    if ($result.mr_url) {
        Write-Host "    MR URL : $($result.mr_url)" -ForegroundColor Cyan
        Write-Host "    PASS — pipeline completed and MR opened!" -ForegroundColor Green
    } elseif ($result.status -eq "skipped") {
        Write-Host "    INFO — Pipeline skipped (no doc-worthy changes found in this commit)." -ForegroundColor DarkYellow
        Write-Host "    Try a commit that adds/changes actual feature behaviour." -ForegroundColor DarkYellow
    } else {
        Write-Host "    Unexpected result: $($result | ConvertTo-Json -Compress)" -ForegroundColor Red
    }
} catch {
    Write-Host "    FAIL — $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails.Message) {
        Write-Host "    Detail: $($_.ErrorDetails.Message)" -ForegroundColor Red
    }
}

Write-Host "`n=== Test 04 Complete ===`n" -ForegroundColor Cyan
Write-Host "Next: run test_02_dashboard.ps1 to see this run in /api/runs" -ForegroundColor DarkYellow
