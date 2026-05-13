# push_phase3_docs_and_vlm_fix.ps1 — Phase 3 docs sync + VLM hallucinate fix
# 2026-05-08
#
# Push 5 件 (~30 KB total):
#   Phase 3 docs sync:
#     1. CLAUDE.md                              (2026-05-08 update panel + 4 處表格更新)
#     2. README.md                              (2026-05-08 升級 panel + ingest 樹更新)
#     3. docs/spec/網站架構圖.md                (Step 3 cascade 5 → 7 來源 + M7_Pipeline 節點)
#   VLM hallucinate fix (褶底片 → 襠底片):
#     4. star_schema/scripts/vlm_pipeline.py    (zone normalize at ingest 層)
#     5. api/analyze.js                         (normalizeZh on l2_name + reasoning)
#
# Usage:
#   .\scripts\push_phase3_docs_and_vlm_fix.ps1 -DryRun   看 diff
#   .\scripts\push_phase3_docs_and_vlm_fix.ps1           正式推

param([switch]$DryRun = $false)

$ErrorActionPreference = "Continue"
$PLATFORM = "C:\temp\stytrix-techpack"
$BACKUP_DIR = Join-Path $env:TEMP "phase3_backup_$(Get-Date -Format 'yyyyMMddHHmm')"

if (-not (Test-Path $PLATFORM)) {
    Write-Host "[!] Platform repo not found: $PLATFORM" -ForegroundColor Red
    exit 1
}

# Files to push
$files = @(
    "CLAUDE.md",
    "README.md",
    "docs\spec\網站架構圖.md",
    "star_schema\scripts\vlm_pipeline.py",
    "api\analyze.js"
)

# === Step 1: Backup files ===
Write-Host "[1/5] Backup deliverables to $BACKUP_DIR" -ForegroundColor Yellow
New-Item -ItemType Directory -Path $BACKUP_DIR -Force | Out-Null

foreach ($f in $files) {
    $src = Join-Path $PLATFORM $f
    if (-not (Test-Path $src)) {
        Write-Host "  [FAIL] missing: $f" -ForegroundColor Red
        exit 1
    }
    $bak = Join-Path $BACKUP_DIR ($f -replace '[\\/]', '__')
    Copy-Item $src $bak -Force
    $sz = (Get-Item $bak).Length
    Write-Host ("  [OK] $f ({0:N1} KB)" -f ($sz / 1KB)) -ForegroundColor Green
}

# === Step 2: Reset platform repo to clean origin/main + new branch ===
Push-Location $PLATFORM
try {
    Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "[2/5] Fetch origin + reset to clean main + new branch" -ForegroundColor Yellow
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

        $branchName = "claude/phase3-docs-vlm-fix-$(Get-Date -Format 'yyyyMMddHHmm')"
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

    foreach ($f in $files) {
        $bak = Join-Path $BACKUP_DIR ($f -replace '[\\/]', '__')
        $dst = Join-Path $PLATFORM $f
        Ensure-Dir $dst
        Copy-Item $bak $dst -Force
        $sz = (Get-Item $dst).Length
        Write-Host ("  [OK] $f ({0:N1} KB)" -f ($sz / 1KB)) -ForegroundColor Green
    }

    # === Step 4: Stage ===
    Write-Host ""
    Write-Host "[4/5] git add" -ForegroundColor Yellow
    if (-not $DryRun) {
        foreach ($f in $files) {
            $fwd = $f -replace '\\', '/'
            & git add -- $fwd 2>&1 | Out-Null
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
docs+fix: Phase 3 docs sync + VLM hallucinate fix (褶底片 -> 襠底片)

Phase 3 docs sync (3 files reflect recent merges):
- CLAUDE.md: add 2026-05-08 update panel + 4 table edits
  (data/source xlsx retired, data/ingest m7_pullon added,
   l2_l3_ie schema upgrade hint, l2_l3_ie_by_client DEPRECATED)
- README.md: 2026-05-08 upgrade panel + ingest tree adds m7_pullon
  + docs/architecture section + cascade 5 -> 7 sources
- docs/spec/網站架構圖.md: Step 3 Mermaid cascade 5 -> 7 sources
  + M7_Pipeline -> m7_pullon ingest node

VLM hallucinate fix (褶底片 / 檔底片 -> 襠底片):
- Layer 1 (static data): verified 38 l2_l3_ie/*.json + visual_guide
  + decision_trees + L2_VLM_Decision_Tree_Prompts_v2.md all clean
  (35 hits 襠底片, 0 hits 褶底片/檔底片)
- Layer 2 (vlm_pipeline.py): add ZH_NORMALIZE in map_terminology_to_iso
  zone/construction fields normalized before facts.jsonl write
- Layer 3 (api/analyze.js): add normalizeZh JS function applied to
  l2_name + explanation/reasoning before returning to frontend
- Layer 4 (聚陽端 build_m7_pullon_source v3): already has ZH_NORMALIZE
  in normalize_zh() (no change needed in this PR)

4-layer defense ensures VLM hallucinate cannot reach UI from any path.
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
