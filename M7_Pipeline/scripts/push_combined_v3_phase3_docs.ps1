# push_combined_v3_phase3_docs.ps1 — 一次推 v3 source + Phase 3 docs + VLM fix + Pipeline mapping skill
# 2026-05-08
#
# 包含:
#   v3 source updates (重新跑 build_m7_pullon_source_v3 後產出):
#     1. data/ingest/m7_pullon/entries.jsonl
#     2. data/ingest/m7_pullon/designs.jsonl.gz
#   Phase 3 docs sync:
#     3. CLAUDE.md
#     4. README.md
#     5. docs/spec/網站架構圖.md
#   VLM hallucinate fix:
#     6. star_schema/scripts/vlm_pipeline.py
#     7. api/analyze.js
#   Pipeline mapping (新):
#     8. docs/architecture/DATA_PIPELINE_MAPPING.md
#
# Usage:
#   .\scripts\push_combined_v3_phase3_docs.ps1 -DryRun
#   .\scripts\push_combined_v3_phase3_docs.ps1

param([switch]$DryRun = $false, [switch]$SkipDesigns = $false)

$ErrorActionPreference = "Continue"
$M7_PIPELINE = "C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\M7_Pipeline"
$PLATFORM = "C:\temp\stytrix-techpack"
$SRC_OUT = Join-Path $M7_PIPELINE "outputs\platform"
$BACKUP_DIR = Join-Path $env:TEMP "combined_backup_$(Get-Date -Format 'yyyyMMddHHmm')"

if (-not (Test-Path $PLATFORM)) {
    Write-Host "[!] Platform repo not found: $PLATFORM" -ForegroundColor Red
    exit 1
}

# Verify v3 source freshly built
$entriesSrc = Join-Path $SRC_OUT "m7_pullon_source.jsonl"
$designsSrc = Join-Path $SRC_OUT "m7_pullon_designs.jsonl"
if (-not (Test-Path $entriesSrc)) {
    Write-Host "[FAIL] $entriesSrc not found - run python scripts\build_m7_pullon_source_v3.py first" -ForegroundColor Red
    exit 1
}
$srcSz = (Get-Item $entriesSrc).Length
if ($srcSz -lt 100000) {
    Write-Host "[FAIL] entries.jsonl too small ($srcSz bytes) - re-run build_m7_pullon_source_v3.py" -ForegroundColor Red
    exit 1
}

# === Step 1: Backup all 8 deliverables to TEMP ===
Write-Host "[1/5] Backup deliverables to $BACKUP_DIR" -ForegroundColor Yellow
New-Item -ItemType Directory -Path $BACKUP_DIR -Force | Out-Null

# 1a. v3 source (from M7 pipeline output)
Copy-Item $entriesSrc (Join-Path $BACKUP_DIR "entries.jsonl") -Force
Write-Host ("  [OK] entries.jsonl ({0:N1} MB)" -f ($srcSz / 1MB)) -ForegroundColor Green

if (-not $SkipDesigns -and (Test-Path $designsSrc)) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $inputBytes = [System.IO.File]::ReadAllBytes($designsSrc)
    $output = [System.IO.MemoryStream]::new()
    $gz = [System.IO.Compression.GZipStream]::new($output, [System.IO.Compression.CompressionMode]::Compress)
    $gz.Write($inputBytes, 0, $inputBytes.Length)
    $gz.Close()
    $compressed = $output.ToArray()
    [System.IO.File]::WriteAllBytes((Join-Path $BACKUP_DIR "designs.jsonl.gz"), $compressed)
    Write-Host ("  [OK] designs.jsonl.gz ({0:N1} MB raw → {1:N1} MB gz)" -f ($inputBytes.Length / 1MB), ($compressed.Length / 1MB)) -ForegroundColor Green
}

# 1b. Platform working tree files (already edited)
$platformFiles = @(
    "CLAUDE.md",
    "README.md",
    "docs\spec\網站架構圖.md",
    "star_schema\scripts\vlm_pipeline.py",
    "api\analyze.js",
    "docs\architecture\DATA_PIPELINE_MAPPING.md"
)
foreach ($f in $platformFiles) {
    $src = Join-Path $PLATFORM $f
    if (-not (Test-Path $src)) {
        Write-Host "  [FAIL] missing in working tree: $f" -ForegroundColor Red
        exit 1
    }
    $bak = Join-Path $BACKUP_DIR ($f -replace '[\\/]', '__')
    Copy-Item $src $bak -Force
    $sz = (Get-Item $bak).Length
    Write-Host ("  [OK] $f ({0:N1} KB)" -f ($sz / 1KB)) -ForegroundColor Green
}

# === Step 2: Reset platform repo + new branch ===
Push-Location $PLATFORM
try {
    Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "[2/5] Fetch + reset to clean main + new branch" -ForegroundColor Yellow
    & git fetch origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] git fetch failed" -ForegroundColor Red
        exit 1
    }

    if (-not $DryRun) {
        & git checkout -- . 2>&1 | Out-Null
        & git clean -fd 2>&1 | Out-Null
        & git checkout main 2>&1 | Out-Null
        & git reset --hard origin/main 2>&1 | Out-Null

        $branchName = "claude/v3-phase3-combined-$(Get-Date -Format 'yyyyMMddHHmm')"
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
    Write-Host "[3/5] Restore deliverables" -ForegroundColor Yellow

    function Ensure-Dir($path) {
        $dir = Split-Path $path -Parent
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    $stagedFiles = @()

    # v3 source files
    $dst = Join-Path $PLATFORM "data\ingest\m7_pullon\entries.jsonl"
    Ensure-Dir $dst
    Copy-Item (Join-Path $BACKUP_DIR "entries.jsonl") $dst -Force
    Write-Host ("  [OK] data\ingest\m7_pullon\entries.jsonl") -ForegroundColor Green
    $stagedFiles += "data/ingest/m7_pullon/entries.jsonl"

    if (-not $SkipDesigns -and (Test-Path (Join-Path $BACKUP_DIR "designs.jsonl.gz"))) {
        $dst = Join-Path $PLATFORM "data\ingest\m7_pullon\designs.jsonl.gz"
        Ensure-Dir $dst
        Copy-Item (Join-Path $BACKUP_DIR "designs.jsonl.gz") $dst -Force
        Write-Host ("  [OK] data\ingest\m7_pullon\designs.jsonl.gz") -ForegroundColor Green
        $stagedFiles += "data/ingest/m7_pullon/designs.jsonl.gz"
    }

    # Platform working-tree files
    foreach ($f in $platformFiles) {
        $bak = Join-Path $BACKUP_DIR ($f -replace '[\\/]', '__')
        $dst = Join-Path $PLATFORM $f
        Ensure-Dir $dst
        Copy-Item $bak $dst -Force
        Write-Host ("  [OK] $f") -ForegroundColor Green
        $stagedFiles += ($f -replace '\\', '/')
    }

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
combined: m7_pullon v3 + Phase 3 docs + VLM fix + DATA_PIPELINE_MAPPING

Sync 8 changes to platform:

1. m7_pullon source updates (build_m7_pullon_source_v3 with pdf_metadata):
   - data/ingest/m7_pullon/entries.jsonl: 7.5 MB / 746 entries (6-dim aggregated)
   - data/ingest/m7_pullon/designs.jsonl.gz: ~6 MB gzipped (3,900 EIDH 履歷
     + new pdf_metadata section from extract_raw_text_m7 metadata-only)

2. Phase 3 docs sync (3 files reflect 5/8 changes):
   - CLAUDE.md: 2026-05-08 update panel + 4 table edits
   - README.md: 2026-05-08 upgrade panel + ingest tree m7_pullon + docs/architecture
   - docs/spec/網站架構圖.md: Step 3 cascade 5 -> 7 sources + M7_Pipeline node

3. VLM hallucinate fix (褶底片 / 檔底片 -> 襠底片):
   - star_schema/scripts/vlm_pipeline.py: ZH_NORMALIZE in map_terminology_to_iso
   - api/analyze.js: normalizeZh applied to l2_name + reasoning text
   - 4-layer defense (static data + ingest + runtime + 聚陽端 v3)

4. NEW: docs/architecture/DATA_PIPELINE_MAPPING.md
   Pinned reference for file × tool × data mapping.
   Mirror of M7_Pipeline/skills/data-pipeline-mapping/SKILL.md (聚陽端).
   Boundary: 聚陽端 push 進 data/ingest/m7_pullon/ 結束;此 doc 從那開始 cover platform 流程。
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
        Write-Host "  Try -SkipDesigns for smaller batch" -ForegroundColor Yellow
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
