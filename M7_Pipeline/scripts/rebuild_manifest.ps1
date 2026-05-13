﻿# rebuild_manifest.ps1 — 用收緊的 detector 重建 callout_manifest.jsonl
# 2026-05-07
#
# 條件：m7_organized_v2/pdf_tp/ 必須有 PDF 原檔（從 SMB 拉下來的）
# 套用 m7_pdf_detect.py 2026-05-07 的 image-type 二次 filter（has ISO / has callout kw / has margin）

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot | Split-Path -Parent
$M7_ORG = Join-Path $ROOT "m7_organized_v2"
$pdfTpDir = Join-Path $M7_ORG "pdf_tp"

Write-Host "ROOT     = $ROOT" -ForegroundColor Cyan
Write-Host "pdf_tp   = $pdfTpDir" -ForegroundColor Cyan

if (-not (Test-Path $pdfTpDir)) {
    Write-Host "[!] $pdfTpDir 不存在，先執行 Phase A (SMB 拉檔) 或 migrate_to_m7_organized.ps1" -ForegroundColor Red
    exit 1
}

$pdfCount = (Get-ChildItem $pdfTpDir -Filter *.pdf -Recurse | Measure-Object).Count
Write-Host "PDF 檔案數: $pdfCount" -ForegroundColor Cyan

if ($pdfCount -eq 0) {
    Write-Host "[!] pdf_tp 下沒 PDF，無法重建 manifest" -ForegroundColor Red
    exit 1
}

# 備份舊 manifest
$mf = Join-Path $M7_ORG "callout_manifest.jsonl"
if (Test-Path $mf) {
    $bk = "$mf.bak_$(Get-Date -Format yyyyMMdd_HHmmss)"
    Copy-Item $mf $bk -Force
    Write-Host "舊 manifest 備份 → $bk" -ForegroundColor DarkGray
}

# 跑 extract_raw_text_m7 重建（只做 PDF，不動 PPTX；--force 蓋舊）
Write-Host ""
Write-Host "[run] extract_raw_text_m7.py --pdf-only --output-dir m7_organized_v2 --force" -ForegroundColor Yellow
Push-Location $ROOT
try {
    & python "scripts\extract_raw_text_m7.py" `
        --scan-dir "$pdfTpDir" `
        --output-dir "$M7_ORG" `
        --pdf-only `
        --force
} finally { Pop-Location }

Write-Host ""
Write-Host "[done] 比對前後狀態：" -ForegroundColor Green
& python (Join-Path $PSScriptRoot "show_vlm_status.py")
