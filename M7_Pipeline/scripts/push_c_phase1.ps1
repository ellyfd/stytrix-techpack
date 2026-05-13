# push_c_phase1.ps1 — C 組 Phase 1a/1b: bucket_taxonomy legacy + m7_pullon source
# 2026-05-08
#
# 推 3 個檔案到 platform repo 一個新 branch 開 PR:
#   1. data/bucket_taxonomy.json (加 legacy_buckets section, +59 alias)
#   2. star_schema/scripts/build_recipes_master.py (load_bucket_taxonomy v4 + build_from_m7_pullon)
#   3. .github/workflows/rebuild_master.yml (trigger paths 加 m7_pullon/)
#
# Strategy:
#   1. Backup 3 modified files to $TEMP\c_phase1
#   2. Stash any other working tree changes
#   3. Checkout new branch from origin/main (clean state)
#   4. Restore 3 files from backup
#   5. Stage + commit + push
#
# 用法: .\scripts\push_c_phase1.ps1 [-DryRun]

param([switch]$DryRun = $false)

$ErrorActionPreference = "Continue"
$PLATFORM = "C:\temp\stytrix-techpack"
$BACKUP_DIR = Join-Path $env:TEMP "c_phase1_backup_$(Get-Date -Format 'yyyyMMddHHmm')"

if (-not (Test-Path $PLATFORM)) {
    Write-Host "[!] Platform repo not found: $PLATFORM" -ForegroundColor Red
    exit 1
}

$files = @(
    "data\bucket_taxonomy.json",
    "star_schema\scripts\build_recipes_master.py",
    ".github\workflows\rebuild_master.yml"
)

Push-Location $PLATFORM
try {
    Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue

    # === Step 1: Backup 3 files to temp ===
    Write-Host "[1/5] Backup edited files to $BACKUP_DIR" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $BACKUP_DIR -Force | Out-Null
    foreach ($f in $files) {
        $src = Join-Path $PLATFORM $f
        if (-not (Test-Path $src)) {
            Write-Host "  [FAIL] missing: $f" -ForegroundColor Red
            exit 1
        }
        $dst = Join-Path $BACKUP_DIR (Split-Path $f -Leaf)
        Copy-Item $src $dst -Force
        $size = (Get-Item $dst).Length
        Write-Host "  [OK] $f ($size bytes)" -ForegroundColor Green
    }

    # === Step 2: Pull latest main ===
    Write-Host ""
    Write-Host "[2/5] Pull latest main" -ForegroundColor Yellow
    & git fetch origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] git fetch failed" -ForegroundColor Red
        exit 1
    }

    # === Step 3: Stash any other changes + checkout new branch ===
    $branchName = "claude/c-phase1-m7-pullon-$(Get-Date -Format 'yyyyMMddHHmm')"
    Write-Host ""
    Write-Host "[3/5] Stash other changes + new branch $branchName" -ForegroundColor Yellow

    if (-not $DryRun) {
        # Stash everything (tracked + untracked) to avoid loss
        & git stash push --include-untracked -m "before-c-phase1-$branchName" 2>&1 | Out-Null
        & git branch -D $branchName 2>&1 | Out-Null
        & git checkout -B $branchName origin/main 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [FAIL] checkout failed" -ForegroundColor Red
            exit 1
        }
        Write-Host "  Branch ready: $branchName" -ForegroundColor Green
    }

    # === Step 4: Restore 3 files from backup ===
    Write-Host ""
    Write-Host "[4/5] Restore patches" -ForegroundColor Yellow
    foreach ($f in $files) {
        $bak = Join-Path $BACKUP_DIR (Split-Path $f -Leaf)
        $dst = Join-Path $PLATFORM $f
        Copy-Item $bak $dst -Force
        Write-Host "  [OK] restored $f" -ForegroundColor Green
        if (-not $DryRun) {
            & git add -- $f 2>&1 | Out-Null
        }
    }

    if ($DryRun) {
        Write-Host ""
        Write-Host "[DryRun] no commit / no push" -ForegroundColor Yellow
        & git --no-pager diff --cached --stat
        exit 0
    }

    # === Step 5: Commit + push ===
    Write-Host ""
    Write-Host "[5/5] Commit + push" -ForegroundColor Yellow
    & git --no-pager diff --cached --stat
    Write-Host ""

    $confirm = Read-Host "Confirm commit + push? (y/n)"
    if ($confirm -ne "y") {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }

    $commitMsg = "feat(data): C Phase 1 - legacy_buckets + m7_pullon source

- bucket_taxonomy.json: add legacy_buckets section (59 old 3-dim names -> expansion)
- build_recipes_master.py: load_bucket_taxonomy handles v4 scalar + legacy
- build_recipes_master.py: add build_from_m7_pullon (graceful when missing)
- rebuild_master.yml: trigger on data/ingest/m7_pullon/ pushes

Scope: construction pipeline only (POM untouched)
Verify: build runs clean, 0 entry loss, m7_pullon=0 (source not yet pushed)"

    & git commit -m $commitMsg
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] commit failed" -ForegroundColor Red
        exit 1
    }
    & git push origin HEAD
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] push failed" -ForegroundColor Red
        Write-Host "  fallback: 用 GitHub web 上傳 or retry .\scripts\push_c_phase1.ps1" -ForegroundColor Yellow
        exit 1
    }

    Write-Host ""
    Write-Host "[OK] Pushed!" -ForegroundColor Green
    Write-Host "Open PR:" -ForegroundColor Cyan
    $prUrl = "https://github.com/ellyfd/stytrix-techpack/compare/main...$branchName" + "?quick_pull=1"
    Write-Host "  $prUrl" -ForegroundColor Cyan
    Start-Process $prUrl

}
finally {
    Pop-Location
}
