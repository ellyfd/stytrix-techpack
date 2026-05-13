﻿# migrate_to_m7_organized.ps1 — 把資料統一到 M7_Pipeline\m7_organized_v2\
# 2026-05-07
#
# 做三件事：
#   1. robocopy callout_images PNG 到 m7_organized_v2/callout_images/
#   2. copy callout_manifest.jsonl / designs.jsonl / vision_facts.jsonl / facts.jsonl / pdf_text_facts.jsonl
#   3. 跑 stats helper 顯示新狀態
#
# 不重建 manifest（要重建用 rebuild_manifest.ps1）；只做 raw migration。

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot | Split-Path -Parent  # M7_Pipeline 根
$M7_ORG = Join-Path $ROOT "m7_organized_v2"
$DL_INGEST = Join-Path (Split-Path $ROOT -Parent) "stytrix-pipeline-Download0504\data\ingest"

Write-Host "ROOT       = $ROOT" -ForegroundColor Cyan
Write-Host "M7_ORG     = $M7_ORG" -ForegroundColor Cyan
Write-Host "DL_INGEST  = $DL_INGEST" -ForegroundColor Cyan
Write-Host ""

# ========== Step 1: 確保結構 ==========
Write-Host "[1/3] Ensure m7_organized_v2/ structure" -ForegroundColor Yellow
$dirs = @("callout_images", "pdf_tp", "ppt_tp", "aligned", "csv_5level", "sketches")
foreach ($d in $dirs) {
    $p = Join-Path $M7_ORG $d
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}

# ========== Step 2: copy data ==========
Write-Host ""
Write-Host "[2/3] Copy data files (PNG / manifest / facts) to m7_organized_v2/" -ForegroundColor Yellow

# 2a. callout_images PNG (用 robocopy mirror)
$pngSrc = Join-Path $DL_INGEST "pdf\callout_images"
$pngDst = Join-Path $M7_ORG "callout_images"
if (Test-Path $pngSrc) {
    Write-Host "  robocopy callout_images:"
    Write-Host "    src: $pngSrc"
    Write-Host "    dst: $pngDst"
    # /MIR mirror; /NFL no file list; /NDL no dir list; /NJH no header; /NJS no summary
    & robocopy $pngSrc $pngDst /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    $n = (Get-ChildItem $pngDst -Filter *.png -ErrorAction SilentlyContinue | Measure-Object).Count
    $sz = (Get-ChildItem $pngDst -Filter *.png -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    if ($null -eq $sz) { $sz = 0 }
    Write-Host ("    done: {0} PNG / {1:N0} MB" -f $n, ($sz / 1MB))
} else {
    Write-Host "  [skip] $pngSrc 不存在" -ForegroundColor DarkGray
}

# 2b. JSONL files
Write-Host ""
$files = @(
    @{ src = "pdf\callout_manifest.jsonl";   dst = "callout_manifest.jsonl"   }
    @{ src = "metadata\designs.jsonl";       dst = "designs.jsonl"            }
    @{ src = "unified\facts.jsonl";          dst = "facts.jsonl"              }
    @{ src = "unified\vision_facts.jsonl";   dst = "vision_facts.jsonl"       }
    @{ src = "unified\pdf_text_facts.jsonl"; dst = "pdf_text_facts.jsonl"     }
)
foreach ($f in $files) {
    $src = Join-Path $DL_INGEST $f.src
    $dst = Join-Path $M7_ORG $f.dst
    if (Test-Path $src) {
        Copy-Item $src $dst -Force
        $sz = (Get-Item $dst).Length
        Write-Host ("  {0,12:N0} bytes → {1}" -f $sz, $f.dst)
    } else {
        Write-Host "  [skip] $($f.src) 不存在" -ForegroundColor DarkGray
    }
}

# ========== Step 3: stats ==========
Write-Host ""
Write-Host "[3/3] Stats" -ForegroundColor Yellow
& python (Join-Path $PSScriptRoot "show_vlm_status.py")

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "Migration done. 接下來步驟："
Write-Host "  (A) 想重建 manifest 套用新 detector：./scripts/rebuild_manifest.ps1"
Write-Host "  (B) 直接用現有 manifest 跑 VLM:"
Write-Host "      python scripts\vlm_fallback_api.py --from-manifest --skip-existing --append --model sonnet"
Write-Host "================================================================" -ForegroundColor Green
