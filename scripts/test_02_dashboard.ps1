# =============================================================================
# TEST 02 — Dashboard Endpoints
# Tests: GET /api/runs   GET /api/health   GET /api/repos
# These are unauthenticated read-only endpoints.
# Expected: 200 with JSON arrays/objects (may be empty on a fresh instance)
# =============================================================================

$BASE = "http://localhost:8080"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " Synkron — Test 02: Dashboard Endpoints" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# --- 1. GET /api/runs ---
Write-Host "[1] GET /api/runs" -ForegroundColor Yellow
try {
    $runs = Invoke-RestMethod -Uri "$BASE/api/runs" -Method Get
    Write-Host "    Returned $($runs.Count) run(s)" -ForegroundColor Green
    if ($runs.Count -gt 0) {
        Write-Host "    Latest run: $($runs[0] | ConvertTo-Json -Compress)" -ForegroundColor DarkGray
    }
    Write-Host "    PASS" -ForegroundColor Green
} catch {
    Write-Host "    FAIL — $($_.Exception.Message)" -ForegroundColor Red
}

# --- 2. GET /api/health ---
Write-Host "`n[2] GET /api/health (run statistics)" -ForegroundColor Yellow
try {
    $stats = Invoke-RestMethod -Uri "$BASE/api/health" -Method Get
    Write-Host "    Stats: $($stats | ConvertTo-Json -Compress)" -ForegroundColor Green
    if ($null -ne $stats.total_runs) {
        Write-Host "    PASS — total_runs=$($stats.total_runs), success_rate=$($stats.success_rate)%" -ForegroundColor Green
    } else {
        Write-Host "    FAIL — missing total_runs field" -ForegroundColor Red
    }
} catch {
    Write-Host "    FAIL — $($_.Exception.Message)" -ForegroundColor Red
}

# --- 3. GET /api/repos ---
Write-Host "`n[3] GET /api/repos" -ForegroundColor Yellow
try {
    $repos = Invoke-RestMethod -Uri "$BASE/api/repos" -Method Get
    Write-Host "    Returned $($repos.Count) repo(s)" -ForegroundColor Green
    if ($repos.Count -gt 0) {
        Write-Host "    First repo: $($repos[0] | ConvertTo-Json -Compress)" -ForegroundColor DarkGray
    }
    Write-Host "    PASS" -ForegroundColor Green
} catch {
    Write-Host "    FAIL — $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n=== Test 02 Complete ===`n" -ForegroundColor Cyan
