"""check_ppt_smb.py — 確認 158 缺檔 EIDH 是 (a) M7 沒 PPT / (b) SMB 抓漏

讀 M7 索引 Excel 的 TP資料夾 欄位（SMB 路徑）+ Test-Path 看是否真的存在。

3 種狀況：
  (a) tp_url 為空 / N/A → M7 系統就沒 PPT，不用補
  (b) tp_url 是 SMB 路徑且 reachable → SMB 真的有，是 reorganize 漏對 → 值得補
  (c) tp_url 是 SMB 路徑但 unreachable → 路徑死掉 / 沒權限

用法：
  python scripts\\check_ppt_smb.py

輸出：
  outputs/ppt_smb_check.csv
"""
from __future__ import annotations
import csv
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MISSING = ROOT / "outputs" / "ppt_missing_eidhs.txt"
OUT = ROOT / "outputs" / "ppt_smb_check.csv"

sys.path.insert(0, str(ROOT / "scripts"))
from m7_eidh_loader import load_m7_index  # noqa: E402


def main():
    if not MISSING.exists():
        print(f"[!] {MISSING} 不存在 — 先跑 audit_ppt_coverage.py")
        sys.exit(1)

    import pandas as pd
    try:
        df = load_m7_index()
    except FileNotFoundError as e:
        print(f"[!] {e}")
        sys.exit(1)

    # Load missing EIDH list
    missing_set = set()
    with open(MISSING, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if parts and parts[0]:
                try:
                    missing_set.add(int(parts[0]))
                except ValueError:
                    pass
    print(f"[load] {len(missing_set)} missing EIDH")

    # Walk index
    rows = []
    for _, row in df.iterrows():
        if not pd.notna(row.get("Eidh")):
            continue
        eidh = int(row["Eidh"])
        if eidh not in missing_set:
            continue
        tp_url = str(row.get("TP資料夾", "") or "").strip()
        m7_url = str(row.get("五階層網址_M7", "") or "").strip()
        customer = str(row.get("客戶", "") or "").strip()
        subgroup = str(row.get("Subgroup", "") or "").strip()
        rows.append({
            "eidh": eidh,
            "customer": customer,
            "subgroup": subgroup,
            "tp_url": tp_url,
            "m7_url": m7_url,
        })

    # Categorize
    print(f"\n[scan] check {len(rows)} EIDH for SMB path status...")
    cat_counter = Counter()
    for r in rows:
        u = r["tp_url"]
        if not u or u in ("N/A", "-", "nan"):
            r["status"] = "no_url_in_index"
        elif u.startswith("\\\\") or u.startswith("//"):
            # SMB UNC path
            try:
                exists = os.path.exists(u)
                # 看是不是有檔
                if exists:
                    items = list(Path(u).iterdir()) if Path(u).is_dir() else [u]
                    n_files = len(items)
                    has_ppt = any(str(p).lower().endswith((".ppt", ".pptx")) for p in items)
                    r["status"] = (
                        "smb_has_ppt" if has_ppt else
                        "smb_exists_no_ppt" if n_files > 0 else
                        "smb_empty"
                    )
                    r["n_files"] = n_files
                else:
                    r["status"] = "smb_unreachable"
            except (OSError, PermissionError) as e:
                r["status"] = f"smb_error:{type(e).__name__}"
        else:
            r["status"] = "url_not_smb"
        cat_counter[r["status"]] += 1

    # Output CSV
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["eidh", "customer", "subgroup", "status", "n_files", "tp_url", "m7_url"],
        )
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in
                        ["eidh", "customer", "subgroup", "status", "n_files", "tp_url", "m7_url"]})

    print(f"\n=== summary ===")
    for status, n in cat_counter.most_common():
        print(f"  {status:30} {n}")
    print(f"\n[output] {OUT}")
    print()
    # Recommend
    no_url = cat_counter.get("no_url_in_index", 0)
    has_ppt = cat_counter.get("smb_has_ppt", 0)
    if has_ppt > no_url:
        print(f"[verdict] (b) SMB 真的有 {has_ppt} 個 PPT 沒抓到 — 值得補")
    elif no_url > has_ppt:
        print(f"[verdict] (a) M7 系統 {no_url} 個 EIDH 本來就沒 PPT — 不用補")
    else:
        print(f"[verdict] 一半一半，看人工判斷")


if __name__ == "__main__":
    main()
