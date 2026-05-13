# push_to_platform.ps1 — 把 A 組產出 sync 到 stytrix-techpack repo + commit + push
# 2026-05-08
#
# 把以下檔案從 M7_Pipeline / Source-Data 同步到 platform repo：
#   1. M7_Pipeline/data/client_canonical_mapping.json (v3) → platform/data/
#   2. M7_Pipeline/outputs/platform/bucket_taxonomy.json (v4) → platform/data/（取代既有）
#   3. Source-Data/MK_METADATA.md → platform/MK_METADATA.md
#   4. Source-Data/STYTRIX_ARCHITECTURE_v1.md → platform/docs/architecture/STYTRIX_ARCHITECTURE.md
#   5. M7_Pipeline/data/client_canonical_mapping_v2.json → platform/data/ingest/m7_pullon/_canonical_v2_backup.json
#
# 用法：.\scripts\push_to_platform.ps1 [-DryRun]

param(
    [switch]$DryRun = $false
)

$ErrorActionPreference = "Continue"  # git stderr informative msgs 不當 error
# 用 .NET Get-Item.Parent 比 Split-Path -Parent 穩定（避免 PowerShell parse 雙 pipeline 失敗）
$SCRIPTS_DIR = $PSScriptRoot
$M7_PIPELINE = (Get-Item $SCRIPTS_DIR).Parent.FullName
$SOURCE_DATA = (Get-Item $M7_PIPELINE).Parent.FullName
$PLATFORM = "C:\temp\stytrix-techpack"

# Helper: 跑 git 並檢查 exit code（不依賴 stderr，看 $LASTEXITCODE）
function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    $output = & git @Args 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[git fail] git $($Args -join ' ')" -ForegroundColor Red
        Write-Host $output -ForegroundColor Red
        throw "git command failed with exit code $LASTEXITCODE"
    }
    return $output
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Push to platform stytrix-techpack" -ForegroundColor Cyan
Write-Host "  M7_PIPELINE: $M7_PIPELINE" -ForegroundColor DarkGray
Write-Host "  SOURCE_DATA: $SOURCE_DATA" -ForegroundColor DarkGray
Write-Host "  PLATFORM:    $PLATFORM" -ForegroundColor DarkGray
Write-Host "  DryRun:      $DryRun" -ForegroundColor $(if ($DryRun) { "Yellow" } else { "Green" })
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $PLATFORM)) {
    Write-Host "[!] Platform repo 不存在：$PLATFORM" -ForegroundColor Red
    Write-Host "    執行: git clone https://github.com/ellyfd/stytrix-techpack $PLATFORM" -ForegroundColor Yellow
    exit 1
}

# === Step 1: 確認本機產出存在 ===
$files = @(
    @{
        src = "$M7_PIPELINE\data\client_canonical_mapping.json"
        dst = "$PLATFORM\data\client_canonical_mapping.json"
        required = $true
        desc = "MK Metadata: 客戶 canonical mapping v3"
    }
    @{
        src = "$M7_PIPELINE\outputs\platform\bucket_taxonomy.json"
        dst = "$PLATFORM\data\bucket_taxonomy.json"
        required = $true
        desc = "MK Metadata: bucket_taxonomy v4 (從 MK 推導)"
    }
    @{
        src = "$SOURCE_DATA\MK_METADATA.md"
        dst = "$PLATFORM\MK_METADATA.md"
        required = $true
        desc = "MK Metadata spec doc"
    }
    @{
        src = "$SOURCE_DATA\STYTRIX_ARCHITECTURE_v1.md"
        dst = "$PLATFORM\docs\architecture\STYTRIX_ARCHITECTURE.md"
        required = $false
        desc = "完整架構 doc v3.0"
    }
    @{
        src = "$SOURCE_DATA\PLATFORM_SYNC_PLAN.md"
        dst = "$PLATFORM\docs\architecture\PLATFORM_SYNC_PLAN.md"
        required = $false
        desc = "同步 plan doc"
    }
)

Write-Host "[1/3] 檢查 source files" -ForegroundColor Yellow
$missing = @()
foreach ($f in $files) {
    if (-not (Test-Path $f.src)) {
        if ($f.required) {
            $missing += $f.src
            Write-Host "  [FAIL] MISSING (required): $($f.src)" -ForegroundColor Red
        } else {
            Write-Host "  [SKIP] MISSING (optional): $($f.src)" -ForegroundColor DarkYellow
        }
    } else {
        $size = (Get-Item $f.src).Length
        Write-Host "  [OK]${size} bytes  $($f.src)" -ForegroundColor Green
    }
}

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "[!] 必需檔案缺，請先跑：" -ForegroundColor Red
    Write-Host "  python scripts\merge_client_metadata_v3.py" -ForegroundColor Yellow
    Write-Host "  python scripts\generate_bucket_taxonomy_from_mk.py" -ForegroundColor Yellow
    exit 1
}

# === Step 2: Copy + git add ===
Write-Host ""
Write-Host "[2/3] Copy + git add" -ForegroundColor Yellow
Push-Location $PLATFORM
try {
    # clean lock
    Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue

    # checkout 新 branch
    $branchName = "claude/v3-mk-metadata-master-$(Get-Date -Format 'yyyyMMddHHmm')"
    if (-not $DryRun) {
        # 已存在 branch 先刪
        & git branch -D $branchName 2>&1 | Out-Null
        & git checkout -b $branchName 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [WARN] git checkout 訊息（informative）" -ForegroundColor DarkYellow
        }
        Write-Host "  Created branch: $branchName" -ForegroundColor Green
    } else {
        Write-Host "  [DryRun] Would create branch: $branchName" -ForegroundColor DarkGray
    }

    foreach ($f in $files) {
        if (-not (Test-Path $f.src)) { continue }
        $dstDir = Split-Path $f.dst -Parent
        if (-not (Test-Path $dstDir)) {
            if (-not $DryRun) {
                New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
            }
        }
        if ($DryRun) {
            Write-Host "  [DryRun] cp $($f.src) -> $($f.dst)" -ForegroundColor DarkGray
        } else {
            Copy-Item $f.src $f.dst -Force
            $relDst = $f.dst.Substring($PLATFORM.Length + 1)
            & git add -- "$relDst" 2>&1 | Out-Null
            Write-Host "  [OK] $relDst -- $($f.desc)" -ForegroundColor Green
        }
    }
}
finally {
    Pop-Location
}

if ($DryRun) {
    Write-Host ""
    Write-Host "[DryRun] 不 commit / push" -ForegroundColor Yellow
    Write-Host "  確認 OK 後再跑：.\scripts\push_to_platform.ps1" -ForegroundColor Yellow
    exit 0
}

# === Step 3: Commit + Push + 開 PR ===
Write-Host ""
Write-Host "[3/3] Commit + Push" -ForegroundColor Yellow
Push-Location $PLATFORM
try {
    git --no-pager diff --cached --stat
    Write-Host ""
    $confirm = Read-Host "確認 commit + push? (y/n)"
    if ($confirm -ne "y") {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }

    $commitMsg = "feat(data): MK Metadata v3 master schema + bucket_taxonomy v4`n`n" +
                 "- client_canonical_mapping.json v3 (38 客戶 4 維 ground truth + legacy fallback)`n" +
                 "- bucket_taxonomy.json v4 (從 MK Metadata cartesian product 推，4 維 key)`n" +
                 "- MK_METADATA.md spec (master schema 6 個元素)`n" +
                 "- STYTRIX_ARCHITECTURE v3.0 (Step 1/2/3/4 framework + maximize info merge)`n`n" +
                 "Scope: 只動做工 pipeline，⛔ POM (pom_rules / gender_gt_pom_rules / etc) 不碰`n" +
                 "Next: build_recipes_master.py 加 build_from_m7_pullon + iso_lookup_merged"
    git commit -m $commitMsg
    git push origin HEAD

    Write-Host ""
    Write-Host "[OK] Pushed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Open PR:" -ForegroundColor Cyan
    Write-Host "  https://github.com/ellyfd/stytrix-techpack/compare/main...$branchName?quick_pull=1" -ForegroundColor Cyan
    Start-Process "https://github.com/ellyfd/stytrix-techpack/compare/main...$branchName?quick_pull=1"
}
finally {
    Pop-Location
}
