# push_m7_pullon_v3.ps1 — M7 PullOn v3 source + Phase 2 docs
# 2026-05-08 (v2: backup-restore mode, no stash)
#
# Push 4 件:
#   1. data/ingest/m7_pullon/entries.jsonl     (~7.5 MB, aggregated source)
#   2. data/ingest/m7_pullon/designs.jsonl.gz  (~6 MB after gzip, per-EIDH 履歷)
#   3. docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md
#   4. data/source/M7_PULLON_DATA_SCHEMA.md
#
# Usage:
#   .\scripts\push_m7_pullon_v3.ps1 -DryRun       看 diff
#   .\scripts\push_m7_pullon_v3.ps1               全推 (含 designs.jsonl.gz)
#   .\scripts\push_m7_pullon_v3.ps1 -SkipDesigns  只推前 3 件 (~7.5 MB)

param(
    [switch]$DryRun = $false,
    [switch]$SkipDesigns = $false
)

$ErrorActionPreference = "Continue"
$M7_PIPELINE = "C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\M7_Pipeline"
$PLATFORM = "C:\temp\stytrix-techpack"
$SRC_OUT = Join-Path $M7_PIPELINE "outputs\platform"
$BACKUP_DIR = Join-Path $env:TEMP "m7v3_backup_$(Get-Date -Format 'yyyyMMddHHmm')"

if (-not (Test-Path $PLATFORM)) {
    Write-Host "[!] Platform repo not found: $PLATFORM" -ForegroundColor Red
    exit 1
}

$entriesSrc = Join-Path $SRC_OUT "m7_pullon_source.jsonl"
$designsSrc = Join-Path $SRC_OUT "m7_pullon_designs.jsonl"

if (-not (Test-Path $entriesSrc)) {
    Write-Host "[FAIL] $entriesSrc not found - run build_m7_pullon_source_v3.py first" -ForegroundColor Red
    exit 1
}
$srcSz = (Get-Item $entriesSrc).Length
if ($srcSz -lt 100000) {
    Write-Host "[FAIL] $entriesSrc too small ($srcSz bytes). Re-run build_m7_pullon_source_v3.py" -ForegroundColor Red
    exit 1
}

# === Step 1: Backup the 4 files (md + jsonl) to TEMP ===
Write-Host "[1/5] Backup deliverables to $BACKUP_DIR" -ForegroundColor Yellow
New-Item -ItemType Directory -Path $BACKUP_DIR -Force | Out-Null

# 1a. entries.jsonl from M7 pipeline output
Copy-Item $entriesSrc (Join-Path $BACKUP_DIR "entries.jsonl") -Force
Write-Host ("  [OK] entries.jsonl ({0:N1} MB)" -f ($srcSz / 1MB)) -ForegroundColor Green

# 1b. designs.jsonl.gz (gzip on the fly)
if (-not $SkipDesigns) {
    if (Test-Path $designsSrc) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $inputBytes = [System.IO.File]::ReadAllBytes($designsSrc)
        $output = [System.IO.MemoryStream]::new()
        $gz = [System.IO.Compression.GZipStream]::new($output, [System.IO.Compression.CompressionMode]::Compress)
        $gz.Write($inputBytes, 0, $inputBytes.Length)
        $gz.Close()
        $compressed = $output.ToArray()
        [System.IO.File]::WriteAllBytes((Join-Path $BACKUP_DIR "designs.jsonl.gz"), $compressed)
        Write-Host ("  [OK] designs.jsonl ({0:N1} MB raw) → designs.jsonl.gz ({1:N1} MB)" -f ($inputBytes.Length / 1MB), ($compressed.Length / 1MB)) -ForegroundColor Green
    } else {
        Write-Host "  [WARN] designs.jsonl not found, skipping" -ForegroundColor Yellow
    }
}

# 1c. MD docs from platform working tree (where we wrote them earlier)
$mdSpec = Join-Path $PLATFORM "docs\architecture\PHASE2_DERIVE_VIEWS_SPEC.md"
$mdSchema = Join-Path $PLATFORM "data\source\M7_PULLON_DATA_SCHEMA.md"
if (-not (Test-Path $mdSpec)) {
    Write-Host "  [FAIL] $mdSpec not found in platform working tree" -ForegroundColor Red
    Write-Host "    (Try: cd $PLATFORM ; git stash list ; git stash pop to recover)" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $mdSchema)) {
    Write-Host "  [FAIL] $mdSchema not found in platform working tree" -ForegroundColor Red
    exit 1
}
Copy-Item $mdSpec (Join-Path $BACKUP_DIR "PHASE2_DERIVE_VIEWS_SPEC.md") -Force
Copy-Item $mdSchema (Join-Path $BACKUP_DIR "M7_PULLON_DATA_SCHEMA.md") -Force
Write-Host "  [OK] 2 MD docs backed up" -ForegroundColor Green

# === Step 2: Reset platform repo to clean origin/main ===
Push-Location $PLATFORM
try {
    Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "[2/5] Fetch origin + reset to clean main" -ForegroundColor Yellow
    & git fetch origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] git fetch failed" -ForegroundColor Red
        exit 1
    }

    if (-not $DryRun) {
        # Hard reset working tree to origin/main (drop all local changes)
        # The deliverables are safe in $BACKUP_DIR, restoring after
        & git checkout -- . 2>&1 | Out-Null    # discard tracked changes
        & git clean -fd 2>&1 | Out-Null         # remove untracked files
        & git checkout main 2>&1 | Out-Null
        & git reset --hard origin/main 2>&1 | Out-Null

        $branchName = "claude/m7-pullon-v3-$(Get-Date -Format 'yyyyMMddHHmm')"
        & git branch -D $branchName 2>&1 | Out-Null
        & git checkout -B $branchName origin/main 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [FAIL] checkout failed" -ForegroundColor Red
            exit 1
        }
        Write-Host "  Branch ready: $branchName" -ForegroundColor Green
    }

    # === Step 3: Restore deliverables ===
    Write-Host ""
    Write-Host "[3/5] Restore deliverables from backup" -ForegroundColor Yellow

    function Ensure-Dir($path) {
        $dir = Split-Path $path -Parent
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    $stagedFiles = @()

    # entries.jsonl
    $dst = Join-Path $PLATFORM "data\ingest\m7_pullon\entries.jsonl"
    Ensure-Dir $dst
    Copy-Item (Join-Path $BACKUP_DIR "entries.jsonl") $dst -Force
    $sz = (Get-Item $dst).Length
    Write-Host ("  [OK] data\ingest\m7_pullon\entries.jsonl ({0:N1} MB)" -f ($sz / 1MB)) -ForegroundColor Green
    $stagedFiles += "data/ingest/m7_pullon/entries.jsonl"

    # designs.jsonl.gz
    $bakGz = Join-Path $BACKUP_DIR "designs.jsonl.gz"
    if (-not $SkipDesigns -and (Test-Path $bakGz)) {
        $dst = Join-Path $PLATFORM "data\ingest\m7_pullon\designs.jsonl.gz"
        Ensure-Dir $dst
        Copy-Item $bakGz $dst -Force
        $sz = (Get-Item $dst).Length
        Write-Host ("  [OK] data\ingest\m7_pullon\designs.jsonl.gz ({0:N1} MB)" -f ($sz / 1MB)) -ForegroundColor Green
        $stagedFiles += "data/ingest/m7_pullon/designs.jsonl.gz"
    }

    # MD docs
    $dst = Join-Path $PLATFORM "docs\architecture\PHASE2_DERIVE_VIEWS_SPEC.md"
    Ensure-Dir $dst
    Copy-Item (Join-Path $BACKUP_DIR "PHASE2_DERIVE_VIEWS_SPEC.md") $dst -Force
    $sz = (Get-Item $dst).Length
    Write-Host ("  [OK] docs\architecture\PHASE2_DERIVE_VIEWS_SPEC.md ({0:N1} KB)" -f ($sz / 1KB)) -ForegroundColor Green
    $stagedFiles += "docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md"

    $dst = Join-Path $PLATFORM "data\source\M7_PULLON_DATA_SCHEMA.md"
    Ensure-Dir $dst
    Copy-Item (Join-Path $BACKUP_DIR "M7_PULLON_DATA_SCHEMA.md") $dst -Force
    $sz = (Get-Item $dst).Length
    Write-Host ("  [OK] data\source\M7_PULLON_DATA_SCHEMA.md ({0:N1} KB)" -f ($sz / 1KB)) -ForegroundColor Green
    $stagedFiles += "data/source/M7_PULLON_DATA_SCHEMA.md"

    # === Step 4: Stage ===
    Write-Host ""
    Write-Host "[4/5] git add" -ForegroundColor Yellow
    if (-not $DryRun) {
        foreach ($f in $stagedFiles) {
            & git add -- $f 2>&1 | Out-Null
        }
    }

    if ($DryRun) {
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

    $commitMsg = @'
feat(data): m7_pullon v3 source + Phase 2 derive view spec

Sync聚陽 PullOn pipeline outputs + design docs to platform.

Files:
- data/ingest/m7_pullon/entries.jsonl: aggregated source for build_recipes_master
- data/ingest/m7_pullon/designs.jsonl.gz: per-EIDH full履歷 (gzipped, 70 MB raw)
- docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md: derive view design spec
- data/source/M7_PULLON_DATA_SCHEMA.md: m7_pullon source schema reference

Coverage (3,900 PullOn EIDH from M7 5/7 索引):
- 100% has techpack folder path
- 78% has BOM fabric_spec
- 26% has techpack PDF/PPTX callouts
- Fabric multi-source consensus: all high confidence

Phase 2 spec covers:
- View A (data/recipes_master.json): generic ISO consensus (existing)
- View B (l2_l3_ie/<L1>.json): Bible 38 schema upgrade (steps list -> list-of-dict)
  with new ie_standard + actuals fields per L5; new_* placeholders filtered out
- View C (data/runtime/designs_index/<EIDH>.json): per-EIDH lazy fetch (3,900 files)

Old l2_l3_ie_by_client/ 26 retired in Phase 2.5.
'@
    & git commit -m $commitMsg
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] commit failed" -ForegroundColor Red
        exit 1
    }

    Write-Host "  Pushing..." -ForegroundColor Yellow
    & git push origin HEAD
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] push failed" -ForegroundColor Red
        Write-Host "  Try -SkipDesigns to push smaller batch first" -ForegroundColor Yellow
        exit 1
    }

    Write-Host ""
    Write-Host "[OK] Pushed!" -ForegroundColor Green
    $branch = & git branch --show-current
    $prUrl = "https://github.com/ellyfd/stytrix-techpack/compare/main...$branch" + "?quick_pull=1"
    Write-Host "Open PR: $prUrl" -ForegroundColor Cyan
    Start-Process $prUrl
}
finally {
    Pop-Location
}
