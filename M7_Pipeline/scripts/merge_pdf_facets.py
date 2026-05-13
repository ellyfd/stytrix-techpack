"""
把 per-brand 的 pdf_facets_<BRAND>.jsonl 合併回中央 pdf_facets.jsonl

⚡ v2 (2026-05-13): UPDATE 語意 — 讀中央既有 + per-brand 覆蓋對應 EIDH + 保留其他
   舊版 (overwrite-all) 會丟掉 per-brand 缺漏的 EIDH (e.g. pdf_facets_DKS.jsonl 只 253 件
   會把中央 2216 件 DKS 蓋成 253). v2 改成 dict-based update 才安全.

跑法: python scripts/merge_pdf_facets.py [--dry-run] [--backup] [--brand BRAND1 BRAND2 ...]

選項:
  --dry-run         只看要合併什麼, 不寫
  --backup          合併前備份中央檔 → pdf_facets.jsonl.bak
  --brand X Y       只合併指定 brand 的 per-brand 檔 (其他保留中央版本)
"""
import argparse
import json
import shutil
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "extract"
TARGET = OUT_DIR / "pdf_facets.jsonl"


def load_jsonl_to_dict(path):
    """Load jsonl, return dict {eidh: entry}."""
    d = {}
    if not path.exists():
        return d
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            eidh = e.get("eidh")
            if eidh:
                d[eidh] = e
    return d


def count_poms(entry):
    if not entry:
        return 0
    mcs = entry.get("measurement_charts") or []
    return sum(len(m.get("poms") or []) for m in mcs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只看要合併什麼, 不寫")
    ap.add_argument("--backup", action="store_true", help="合併前備份舊中央檔")
    ap.add_argument("--brand", nargs="*", help="只合併指定 brand (大寫). 不指定 = 全合.")
    args = ap.parse_args()

    target_brands = set(b.upper() for b in args.brand) if args.brand else None

    per_brand_files = sorted(OUT_DIR.glob("pdf_facets_*.jsonl"))
    per_brand_files = [f for f in per_brand_files if f.name != "pdf_facets.jsonl"]
    if target_brands:
        per_brand_files = [
            f for f in per_brand_files
            if f.stem.replace("pdf_facets_", "") in target_brands
        ]

    if not per_brand_files:
        print(f"[!] {OUT_DIR} 找不到任何符合條件的 pdf_facets_*.jsonl")
        return 1

    # === 1. 載入中央既有資料 ===
    print(f"[load] 中央 {TARGET.name}: ", end="", flush=True)
    central = load_jsonl_to_dict(TARGET)
    central_poms_before = sum(count_poms(e) for e in central.values())
    central_brand_before = Counter()
    for e in central.values():
        cl = e.get("client_code")
        if cl:
            central_brand_before[cl] += 1
    print(f"{len(central):,} entries / {central_poms_before:,} POMs")

    # === 2. 預覽 per-brand 檔案要做什麼 ===
    print(f"\n[scan] 找到 {len(per_brand_files)} 個 per-brand 檔:")
    pb_data = {}
    for f in per_brand_files:
        bcode = f.stem.replace("pdf_facets_", "")
        d = load_jsonl_to_dict(f)
        pb_data[bcode] = d
        size_mb = f.stat().st_size // 1024 // 1024
        # 對比中央既有
        central_n = central_brand_before.get(bcode, 0)
        delta = len(d) - central_n
        delta_str = f"({'+' if delta >= 0 else ''}{delta} vs 中央)"
        print(f"  {bcode:<10} {len(d):>5} entries  {size_mb:>4} MB  {delta_str}")

    if args.dry_run:
        print(f"\n[dry-run] 不寫, 預期: {len(central):,} 中央 entries 中, "
              f"{sum(len(d) for d in pb_data.values()):,} 件會被替換/新增")
        return 0

    # === 3. UPDATE 中央: per-brand entries 替換對應 EIDH ===
    if args.backup and TARGET.exists():
        backup = TARGET.with_suffix(".jsonl.bak")
        print(f"\n[backup] {TARGET.name} → {backup.name}")
        shutil.copy2(TARGET, backup)

    n_replaced = 0
    n_added = 0
    per_brand_pom_diff = {}
    for bcode, d in sorted(pb_data.items()):
        old_b_pom = sum(count_poms(central[e]) for e in d if e in central)
        replaced = 0
        added = 0
        for eidh, entry in d.items():
            if eidh in central:
                replaced += 1
            else:
                added += 1
            central[eidh] = entry
        new_b_pom = sum(count_poms(d[e]) for e in d)
        per_brand_pom_diff[bcode] = (old_b_pom, new_b_pom, replaced, added)
        n_replaced += replaced
        n_added += added

    # === 4. 寫回中央 (atomic via tmp) ===
    tmp = TARGET.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as fout:
        for entry in central.values():
            fout.write(json.dumps(entry, ensure_ascii=False) + "\n")
    tmp.replace(TARGET)

    # === 5. Summary ===
    central_poms_after = sum(count_poms(e) for e in central.values())
    out_mb = TARGET.stat().st_size // 1024 // 1024
    print(f"\n=== Merge Summary ===")
    print(f"  Total entries: {len(central):,} ({out_mb} MB)")
    print(f"  Replaced:      {n_replaced:,}")
    print(f"  Added:         {n_added:,}")
    print(f"  Total POMs:    {central_poms_before:,} → {central_poms_after:,} "
          f"({central_poms_after - central_poms_before:+,})")

    print(f"\n=== Per-brand POM diff ===")
    for bcode in sorted(per_brand_pom_diff.keys()):
        old, new, r, a = per_brand_pom_diff[bcode]
        diff = new - old
        sign = "+" if diff >= 0 else ""
        flag = " ⚠️" if diff < -1000 else ""
        print(f"  {bcode:<10} {r:>4}r {a:>4}a  POM: {old:>7,} → {new:>7,}  ({sign}{diff:>+,}){flag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
