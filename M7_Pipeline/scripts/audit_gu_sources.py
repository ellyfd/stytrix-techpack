"""
查 GU 在 PDF / PPTX / XLSX 三源的真實狀態
GU 是日本 UNIQLO sister brand, PPTX 可能是日文式樣書, 中文 keyword 抽不到
跑法: python scripts\audit_gu_sources.py
"""
import json
import os
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "extract"
TP = ROOT / "tp_samples_v2"

def file_stats_for_brand(brand="GU"):
    """掃 tp_samples_v2/<EIDH> 計 GU 各檔案類型實際數量"""
    print(f"\n=== {brand} tp_samples_v2 file inventory ===")
    if not TP.exists():
        print(f"  [!] {TP} 不存在")
        return
    n_folders = 0
    n_pdf = 0
    n_pptx = 0
    n_xlsx = 0
    folders_with_pptx = 0
    folders_with_pdf = 0
    folders_with_xlsx = 0
    sample_pptx_names = []
    # We need to map folder → brand. Read pdf_facets to get client_code per EIDH
    eidh_to_brand = {}
    for f in [OUT / "pdf_facets.jsonl", OUT / "pptx_facets.jsonl", OUT / "xlsx_facets.jsonl"]:
        if not f.exists(): continue
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except: continue
                eidh = d.get("eidh")
                cl = d.get("client_code")
                if eidh and cl:
                    eidh_to_brand[eidh] = cl

    for folder in TP.iterdir():
        if not folder.is_dir(): continue
        eidh = folder.name.split("_")[0]
        if eidh_to_brand.get(eidh) != brand: continue
        n_folders += 1
        pdfs = list(folder.rglob("*.pdf"))
        pptxs = list(folder.rglob("*.pptx"))
        xlsxs = list(folder.rglob("*.xlsx")) + list(folder.rglob("*.xls"))
        n_pdf += len(pdfs)
        n_pptx += len(pptxs)
        n_xlsx += len(xlsxs)
        if pdfs: folders_with_pdf += 1
        if pptxs: folders_with_pptx += 1
        if xlsxs: folders_with_xlsx += 1
        if pptxs and len(sample_pptx_names) < 10:
            sample_pptx_names.extend([p.name for p in pptxs[:2]])

    print(f"  {brand} 總資料夾數         : {n_folders:,}")
    print(f"  含 PDF 的資料夾         : {folders_with_pdf:,} ({folders_with_pdf/max(n_folders,1)*100:.0f}%)")
    print(f"  含 PPTX 的資料夾        : {folders_with_pptx:,} ({folders_with_pptx/max(n_folders,1)*100:.0f}%)")
    print(f"  含 XLSX 的資料夾        : {folders_with_xlsx:,} ({folders_with_xlsx/max(n_folders,1)*100:.0f}%)")
    print(f"  PDF 檔案數              : {n_pdf:,}")
    print(f"  PPTX 檔案數             : {n_pptx:,}")
    print(f"  XLSX 檔案數             : {n_xlsx:,}")
    print(f"  PPTX 檔名樣本 (前 10):")
    for n in sample_pptx_names[:10]:
        print(f"    - {n}")

def facet_stats_for_brand(brand="GU"):
    """看 GU 在 3 個 facets jsonl 各抽到什麼"""
    print(f"\n=== {brand} facet 抽取結果 ===")
    for f, key in [
        (OUT / "pdf_facets.jsonl", "pdf"),
        (OUT / "pptx_facets.jsonl", "pptx"),
        (OUT / "xlsx_facets.jsonl", "xlsx"),
    ]:
        if not f.exists():
            print(f"  {f.name}: 不存在")
            continue
        n_total = 0
        n_with_data = 0
        n_with_callout = 0
        n_with_mc = 0
        n_with_meta = 0
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except: continue
                if d.get("client_code") != brand: continue
                n_total += 1
                # 2026-05-12 rename: 同時讀新舊 key
                # PDF: construction_pages, PPTX: constructions
                has_construction = bool(d.get("construction_pages") or d.get("constructions") or d.get("callouts"))
                if has_construction: n_with_callout += 1
                if d.get("measurement_charts"): n_with_mc += 1
                if d.get("metadata"): n_with_meta += 1
                if any([has_construction, d.get("measurement_charts"), d.get("metadata"), d.get("construction_iso_map")]):
                    n_with_data += 1
        print(f"  {f.name:<22} {brand}={n_total:>5}  with_data={n_with_data:>5}  callout={n_with_callout:>5}  mc={n_with_mc:>4}  meta={n_with_meta:>4}")

def sample_pptx_text(brand="GU"):
    """抓 GU PPTX 原始 text 看是中文/日文/英文"""
    pptx_text_dir = OUT / "pptx_text"
    if not pptx_text_dir.exists():
        print(f"\n=== {brand} PPTX 原始 text 樣本 ===")
        print(f"  [!] {pptx_text_dir} 不存在")
        return
    print(f"\n=== {brand} PPTX 原始 text 樣本 (前 3 個檔, 各 500 字) ===")
    n = 0
    for txt in pptx_text_dir.glob(f"{brand}_*.txt"):
        if n >= 3: break
        try:
            content = txt.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  [!] {txt.name} 讀取失敗: {e}")
            continue
        print(f"\n  --- {txt.name} ({len(content)} chars) ---")
        print(f"  {content[:500]}")
        print(f"  ... (省略)")
        n += 1
    if n == 0:
        print(f"  沒找到 {brand}_*.txt — 表示 GU 沒抽出任何 PPTX text")

if __name__ == "__main__":
    file_stats_for_brand("GU")
    facet_stats_for_brand("GU")
    sample_pptx_text("GU")
    print()
