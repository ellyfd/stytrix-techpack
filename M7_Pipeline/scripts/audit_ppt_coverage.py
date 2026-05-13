"""audit_ppt_coverage.py — 比對 M7 索引 1180 EIDH vs ppt_tp/ 實際檔案

找出哪 158 EIDH 沒 PPT。原因可能：
  1. SMB copy 過程漏抓
  2. 該 EIDH 在 M7 系統就沒 PPT 上傳（只有 PDF / 純報價）
  3. 命名規則 mismatch（reorganize 步驟漏對到）

輸出：
  outputs/ppt_coverage_audit.csv  — 每 EIDH 一行（has_ppt yes/no）
  outputs/ppt_missing_eidhs.txt   — 沒 PPT 的 EIDH 純文字 list（給後續補抓用）

用法：
  python scripts\\audit_ppt_coverage.py
"""
from __future__ import annotations
import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PPT_DIR = ROOT / "m7_organized_v2" / "ppt_tp"           # 扁平 (pipeline 解析用)
TP_SAMPLES_DIR = ROOT / "tp_samples_v2"                  # 按 design 分子資料夾 (原始 sample)
OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CSV = OUT_DIR / "ppt_coverage_audit.csv"
MISSING_TXT = OUT_DIR / "ppt_missing_eidhs.txt"

sys.path.insert(0, str(ROOT / "scripts"))
from m7_eidh_loader import load_m7_index  # noqa: E402


def load_index_eidhs():
    """從 M7 索引 Excel 讀 EIDH + metadata（套 ITEM_FILTER）"""
    try:
        df = load_m7_index()
    except FileNotFoundError as e:
        print(f"[!] {e}")
        sys.exit(1)
    import pandas as pd
    out = []
    for _, row in df.iterrows():
        eidh = row.get("Eidh")
        if not pd.notna(eidh):
            continue
        out.append({
            "eidh": int(eidh),
            "customer": str(row.get("客戶", row.get("Customer", "")) or "").strip(),
            "subgroup": str(row.get("Subgroup", "") or "").strip(),
            "style_no": str(row.get("報價款號", row.get("Style#", row.get("Style No", ""))) or "").strip(),
            "season": str(row.get("Season", "") or "").strip(),
            "item": str(row.get("Item", "") or "").strip(),
            "program": str(row.get("Program", "") or "").strip(),
            "wk": str(row.get("W/K", "") or "").strip(),
        })
    return out


def list_ppt_files():
    """合併兩邊：m7_organized_v2/ppt_tp/ (扁平) + tp_samples_v2/{eidh}/* (按 design)
    → {eidh: [files]}（合併兩邊有的所有 PPT 檔名）
    """
    out: dict[int, list[str]] = {}
    eidh_re = re.compile(r"^(\d{6})")
    # 1. flat folder
    if PPT_DIR.exists():
        for p in PPT_DIR.iterdir():
            if not p.is_file() or p.suffix.lower() not in (".ppt", ".pptx"):
                continue
            m = eidh_re.match(p.name)
            if m:
                out.setdefault(int(m.group(1)), []).append(f"flat/{p.name}")
    # 2. tp_samples_v2 subfolders
    if TP_SAMPLES_DIR.exists():
        for sub in TP_SAMPLES_DIR.iterdir():
            if not sub.is_dir():
                continue
            m = eidh_re.match(sub.name)
            if not m:
                continue
            eidh = int(m.group(1))
            for p in sub.iterdir():
                if p.is_file() and p.suffix.lower() in (".ppt", ".pptx"):
                    out.setdefault(eidh, []).append(f"samples/{sub.name}/{p.name}")
    return out


def main():
    print(f"[1] load M7 索引 EIDHs from {M7_INDEX.name}")
    index_rows = load_index_eidhs()
    print(f"    {len(index_rows)} EIDH in index")

    print(f"\n[2] scan PPT (兩邊合併)")
    print(f"    flat:    {PPT_DIR}")
    print(f"    samples: {TP_SAMPLES_DIR}")
    ppt_by_eidh = list_ppt_files()
    print(f"    {len(ppt_by_eidh)} unique EIDH have PPT (union)")

    print(f"\n[3] cross-check")
    missing = []
    have = []
    for r in index_rows:
        if r["eidh"] in ppt_by_eidh:
            have.append(r["eidh"])
        else:
            missing.append(r)

    print(f"    have PPT:    {len(have):4} ({len(have)/len(index_rows)*100:.1f}%)")
    print(f"    missing PPT: {len(missing):4} ({len(missing)/len(index_rows)*100:.1f}%)")

    # CSV 輸出
    with open(CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["eidh", "has_ppt", "n_files", "customer", "subgroup", "style_no", "season", "item", "files"])
        for r in index_rows:
            files = ppt_by_eidh.get(r["eidh"], [])
            w.writerow([r["eidh"], "Y" if files else "N", len(files),
                        r["customer"], r["subgroup"], r["style_no"], r["season"], r["item"],
                        " | ".join(files[:3])])
    print(f"\n[output] {CSV}")

    with open(MISSING_TXT, "w", encoding="utf-8") as f:
        for r in missing:
            f.write(f"{r['eidh']}\t{r['customer']}\t{r['subgroup']}\t{r['style_no']}\n")
    print(f"[output] {MISSING_TXT}")

    # 缺檔分析：哪些客戶 / subgroup 缺最多
    print(f"\n[4] missing breakdown")
    miss_client = Counter(r["customer"] for r in missing)
    print(f"  missing by customer (top 10):")
    for c, n in miss_client.most_common(10):
        print(f"    {c[:30]:30} {n}")

    miss_sg = Counter((r["customer"][:20], r["subgroup"][:20]) for r in missing)
    print(f"\n  missing by (customer, subgroup) top 10:")
    for (c, sg), n in miss_sg.most_common(10):
        print(f"    {c:21} / {sg:21} {n}")


if __name__ == "__main__":
    main()
