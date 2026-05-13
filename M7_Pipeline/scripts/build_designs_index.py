"""build_designs_index.py — Phase 2 View C:per-EIDH designs_index JSON

讀 m7_pullon_designs.jsonl(3900 件 / 78 MB 單檔)+ Bible(stytrix-techpack/l2_l3_ie/<L1>.json),
輸出 outputs/platform/designs_index/<EIDH>.json,每 EIDH 1 個 small JSON(~5-20 KB)。

每筆 EIDH JSON schema:
{
  "eidh": "311320",
  "design_id": "510383_FA25",
  "client": {"name": "OLD NAVY", "code": "ONY"},
  "canonical": {...},                  # 8 canonical (value, confidence, sources)
  "classification": {...},             # gender / dept / gt / it / subgroup / program / item
  "fabric": {...},                     # multi-source consensus (KNIT/WOVEN)
  "five_level": [
    {
      "row_index": 1, "category_zh": "腰頭",
      "l1": "WB", "l2": "...", "l3": "...", "l4": "...", "l5": "...",
      "primary": "...", "skill": "...", "machine": "...", "size": "-", "sec": 5.0,
      "bible_alignment": {"in_bible": true, "type": "match", "level_breaks_at": null}
    },
    ...
  ],
  "ie_breakdown": {...},               # sewing_ie / cutting_ie / 等
  "order": {...},                      # quantity_dz / fabric_spec / 等
  "techpack_coverage": {...},
  "sources": {...},
  "_alignment_summary": {              # Phase 2 新增
    "n_steps": 62,
    "n_match": 50,
    "n_mismatch": 12,
    "match_pct": 80.6,
    "by_type": {"match": 50, "A": 8, "B": 2, "C": 1, "other": 1}
  },
  "_metadata": {...}
}

跑:python scripts/build_designs_index.py [--bible-root <path>] [--limit N]
Output dir: outputs/platform/designs_index/<EIDH>.json
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from bible_classify import load_bible, step_alignment  # noqa: E402

DESIGNS = ROOT / "outputs" / "platform" / "m7_pullon_designs.jsonl"
DEFAULT_BIBLE_ROOT = Path(r"C:\temp\stytrix-techpack\l2_l3_ie")
OUT_DIR = ROOT / "outputs" / "platform" / "designs_index"
INDEX_FILE = OUT_DIR / "_index.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bible-root", default=str(DEFAULT_BIBLE_ROOT))
    ap.add_argument("--limit", type=int, default=0, help="只產前 N 筆(0=全跑)")
    ap.add_argument("--clean", action="store_true",
                   help="先砍 designs_index/ 整個資料夾再重產")
    args = ap.parse_args()

    bible = load_bible(Path(args.bible_root))
    print(f"[bible] {bible['n_files']} L1 files / {len(bible['full_tuples']):,} canonical tuples")

    if not DESIGNS.exists():
        print(f"[FAIL] {DESIGNS} not found")
        return 1

    if args.clean and OUT_DIR.exists():
        print(f"[clean] removing {OUT_DIR}")
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # === Walk designs ===
    print(f"[walk] {DESIGNS.relative_to(ROOT)}")
    n_designs = 0
    n_written = 0
    n_skipped = 0
    type_total = Counter()
    index_entries = []  # 給 _index.json 用

    with open(DESIGNS, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            n_designs += 1
            if args.limit and n_written >= args.limit:
                break

            eidh = str(d.get("eidh", ""))
            if not eidh:
                n_skipped += 1
                continue
            fabric = (d.get("fabric") or {}).get("value", "").lower()
            steps = d.get("five_level_steps") or []

            # Add bible_alignment per step
            new_steps = []
            type_counter = Counter()
            for s in steps:
                align = step_alignment(s, fabric, bible)
                type_counter[align["type"]] += 1
                type_total[align["type"]] += 1
                new_steps.append({**s, "bible_alignment": align})

            n_steps = len(new_steps)
            n_match = type_counter["match"]

            # === 組 per-EIDH JSON ===
            entry = {
                "eidh": eidh,
                "design_id": d.get("design_id"),
                "style_no_internal": d.get("style_no_internal"),
                "season": d.get("season"),
                "client": d.get("client"),
                "canonical": d.get("canonical"),
                "classification": d.get("classification"),
                "fabric": d.get("fabric"),
                "five_level": new_steps,
                "n_steps": n_steps,
                "ie_total_seconds": d.get("ie_total_seconds"),
                "techpack_coverage": d.get("techpack_coverage"),
                "order": d.get("order"),
                "ie_breakdown_summary": d.get("ie_breakdown_summary"),
                "pdf_metadata": d.get("pdf_metadata"),
                "pdf_canonical": d.get("pdf_canonical"),
                "_alignment_summary": {
                    "n_steps": n_steps,
                    "n_match": n_match,
                    "n_mismatch": n_steps - n_match,
                    "match_pct": round(100 * n_match / n_steps, 1) if n_steps else 0,
                    "by_type": dict(type_counter),
                },
                "sources": d.get("sources"),
                "_metadata": {
                    "build_version": "v8_designs_index",
                    "view": "View C: per-EIDH lazy-fetch index",
                    "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "bible_canonical_tuples": len(bible["full_tuples"]),
                },
            }

            # 寫檔
            out_path = OUT_DIR / f"{eidh}.json"
            out_path.write_text(json.dumps(entry, ensure_ascii=False, default=str),
                                encoding="utf-8")
            n_written += 1

            # 給 _index.json 用的 light entry(filter / list 用)
            index_entries.append({
                "eidh": eidh,
                "design_id": d.get("design_id"),
                "client_code": (d.get("client") or {}).get("code"),
                "canonical_客戶": ((d.get("canonical") or {}).get("客戶") or {}).get("value"),
                "canonical_W/K": ((d.get("canonical") or {}).get("W/K") or {}).get("value"),
                "canonical_PRODUCT_CATEGORY": ((d.get("canonical") or {}).get("PRODUCT_CATEGORY") or {}).get("value"),
                "canonical_Item": ((d.get("canonical") or {}).get("Item") or {}).get("value"),
                "canonical_Season": ((d.get("canonical") or {}).get("Season") or {}).get("value"),
                "n_steps": n_steps,
                "ie_total_seconds": d.get("ie_total_seconds"),
                "alignment_match_pct": round(100 * n_match / n_steps, 1) if n_steps else 0,
                "file": f"{eidh}.json",
            })

    # === 寫 _index.json ===
    INDEX_FILE.write_text(
        json.dumps({
            "n_entries": len(index_entries),
            "_metadata": {
                "build_version": "v8_designs_index",
                "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "view": "View C: per-EIDH lazy-fetch designs index",
                "schema_note": "前端 fetch _index.json 拿 light list 做 filter,點開某筆再 fetch <EIDH>.json 拿完整履歷",
            },
            "entries": index_entries,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 統計輸出
    total_size = sum((OUT_DIR / e["file"]).stat().st_size for e in index_entries)
    avg_size = total_size / len(index_entries) if index_entries else 0
    idx_size = INDEX_FILE.stat().st_size

    print()
    print(f"=== Done ===")
    print(f"  n_designs read:        {n_designs:>6,}")
    print(f"  n_index entries:       {n_written:>6,}")
    print(f"  n_skipped (no EIDH):   {n_skipped:>6,}")
    print(f"  per-EIDH avg size:     {avg_size/1024:>6.1f} KB")
    print(f"  total per-EIDH:        {total_size/1024/1024:>6.1f} MB")
    print(f"  _index.json size:      {idx_size/1024/1024:>6.2f} MB")
    print(f"  output dir:            {OUT_DIR}")
    print()
    print(f"=== Bible alignment stats ===")
    n_steps_total = sum(type_total.values())
    for t in ["match", "A", "B", "C", "other"]:
        n = type_total[t]
        pct = 100 * n / n_steps_total if n_steps_total else 0
        label = {"match": "match", "A": "Type A broad", "B": "Type B placeholder",
                "C": "Type C *_其它", "other": "Type other"}[t]
        print(f"  {label:25} {n:>9,}  ({pct:>5.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
