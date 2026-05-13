﻿# 2_fetch_tp.ps1 — M7 TP folder copier
# ====================================================
# 從 m7_organized_v2/_fetch_manifest.csv 讀 EIDH + TP資料夾 路徑，
# 複製 TP 資料夾內的 PDF/PPTX/XLSX 到 tp_samples_v2/<EIDH>_<款號>/
# 用法：.\scripts\2_fetch_tp.ps1
# 或指定 manifest：.\scripts\2_fetch_tp.ps1 -ManifestPath "C:\path\to\manifest.csv"

param(
    [string]$ManifestPath,
    [string]$DestRoot
)

# 2026-05-11: $PSScriptRoot 在 param() default 內某些 PS 版本 parse 失敗,改到 body 處理
if (-not $ManifestPath) {
    $ManifestPath = Join-Path $PSScriptRoot '..\m7_organized_v2\_fetch_manifest.csv'
}
if (-not $DestRoot) {
    $DestRoot = Join-Path $PSScriptRoot '..\tp_samples_v2'
}

if (-not (Test-Path $ManifestPath)) {
    Write-Host "[FAIL] manifest not found: $ManifestPath" -ForegroundColor Red
    Write-Host "       請先跑 1_fetch.py 產生 _fetch_manifest.csv"
    exit 1
}

$rows = Import-Csv -Path $ManifestPath
Write-Host "[load] manifest: $($rows.Count) EIDH" -ForegroundColor Cyan

New-Item -ItemType Directory -Path $DestRoot -Force | Out-Null

$ok = 0
$fail = 0
$noPath = 0

foreach ($r in $rows) {
    $eidh = $r.Eidh
    $style = $r.'報價款號'
    $tpPath = $r.'TP資料夾'

    if ([string]::IsNullOrWhiteSpace($tpPath)) {
        $noPath++
        continue
    }

    # 安全檔名：去掉特殊字元
    $safeStyle = $style -replace '[\\/:*?"<>|]', '_'
    $sub = Join-Path $DestRoot "$($eidh)_$safeStyle"
    New-Item -ItemType Directory -Path $sub -Force | Out-Null

    Write-Host ""
    Write-Host "=== EIDH $eidh / $style ===" -ForegroundColor Cyan
    Write-Host "  TP: $tpPath"

    if (Test-Path $tpPath) {
        $files = Get-ChildItem -Path $tpPath -File -Recurse -Include *.pdf,*.pptx,*.ppt,*.xlsx -ErrorAction SilentlyContinue
        if ($files.Count -eq 0) {
            Write-Host "  [INFO] folder exists but no PDF/PPTX/XLSX found" -ForegroundColor Yellow
            continue
        }
        Write-Host ("  -> " + $files.Count + " files") -ForegroundColor Green
        foreach ($f in $files) {
            try {
                Copy-Item -Path $f.FullName -Destination $sub -Force
                $sizeKB = [math]::Round($f.Length / 1KB, 1)
                Write-Host ("    [OK] " + $f.Name + "  (" + $sizeKB + " KB)")
                $ok++
            } catch {
                Write-Host ("    [FAIL] " + $f.Name + " : " + $_.Exception.Message) -ForegroundColor Red
                $fail++
            }
        }
    } else {
        Write-Host "  [FAIL] path not accessible" -ForegroundColor Red
        $fail++
    }
}

$totalSize = (Get-ChildItem -Path $DestRoot -File -Recurse -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1MB

Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
Write-Host "DONE: $DestRoot" -ForegroundColor Green
Write-Host ("  copied: $ok files")
Write-Host ("  failed: $fail")
Write-Host ("  empty TP path in manifest: $noPath")
Write-Host ("  Total size: " + [math]::Round($totalSize, 1) + " MB")
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
