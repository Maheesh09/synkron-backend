# =============================================================================
# TEST 01 — Health & Root Endpoints
# Tests: GET /  and  GET /health
# Expected: Both return 200 with JSON bodies
# =============================================================================

$BASE = "http://localhost:8080"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " Synkron — Test 01: Health Checks" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# --- 1. Root ---
Write-Host "[1] GET / (service info)" -ForegroundColor Yellow
$r = Invoke-RestMethod -Uri "$BASE/" -Method Get
Write-Host "    Response: $($r | ConvertTo-Json -Compress)" -ForegroundColor Green
if ($r.service -eq "synkron" -and $r.status -eq "running") {
    Write-Host "    PASS" -ForegroundColor Green
} else {
    Write-Host "    FAIL — unexpected body" -ForegroundColor Red
}

# --- 2. Health ---
Write-Host "`n[2] GET /health" -ForegroundColor Yellow
$r2 = Invoke-RestMethod -Uri "$BASE/health" -Method Get
Write-Host "    Response: $($r2 | ConvertTo-Json -Compress)" -ForegroundColor Green
if ($r2.status -eq "healthy") {
    Write-Host "    PASS" -ForegroundColor Green
} else {
    Write-Host "    FAIL — status not 'healthy'" -ForegroundColor Red
}

Write-Host "`n=== Test 01 Complete ===`n" -ForegroundColor Cyan
