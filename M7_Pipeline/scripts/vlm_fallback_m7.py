"""vlm_fallback_m7.py — Vision fallback workflow（Read tool 版，不用 API key）

對 0-fact image-only PDF design（圖層 callout，text-layer 抽不到）：
  1. 列出候選 design 的 PNG 路徑（給 Claude Cowork Read tool 用）
  2. 人工 / Claude Read tool 逐張看 PNG，抽 callout 文字 → facts
  3. facts 寫進 vision_facts.jsonl（手寫或半自動）
  4. 用 merge mode 驗 schema 後 append 進 facts.jsonl

vision_facts.jsonl schema（跟 unified facts.jsonl 一致）：
  {"zone_zh": "腰頭", "l1_code": "WB", "iso": "514", "combo": "514+605",
   "method": "四線拷克 + 三針五線爬網(514+605)", "confidence": "vision",
   "source_line": "W/B SEAM: ISO 514+605",
   "design_id": "D97929", "bucket": "WOVEN_BOTTOMS", "gt_group": "BOTTOMS",
   "source": "vision", "client": "ONY", "eidh": 327840}

用法：
  python scripts/vlm_fallback_m7.py --mode list [--client ONY] [--limit 20]
  python scripts/vlm_fallback_m7.py --mode merge [--vision-file PATH] [--dry-run]
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 2026-05-07：統一資料源 → M7_Pipeline/m7_organized_v2/
M7_ORG = ROOT / "m7_organized_v2"
DL = ROOT.parent / "stytrix-pipeline-Download0504"  # legacy fallback
DESIGNS_CSV = ROOT / "outputs" / "zero_fact_pdfs" / "_designs.csv"
PNG_DIR = M7_ORG / "callout_images" if (M7_ORG / "callout_images").exists() and any((M7_ORG / "callout_images").iterdir()) else DL / "data" / "ingest" / "pdf" / "callout_images"
DESIGNS_JSONL = M7_ORG / "designs.jsonl" if (M7_ORG / "designs.jsonl").exists() else DL / "data" / "ingest" / "metadata" / "designs.jsonl"
UNIFIED_FACTS = M7_ORG / "facts.jsonl" if (M7_ORG / "facts.jsonl").exists() else DL / "data" / "ingest" / "unified" / "facts.jsonl"
VISION_FACTS = M7_ORG / "vision_facts.jsonl" if (M7_ORG / "vision_facts.jsonl").exists() else DL / "data" / "ingest" / "unified" / "vision_facts.jsonl"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m7_constants import derive_bucket, derive_gt_group  # noqa: E402


def cmd_list(args):
    """列出 0-fact image-only design 的 PNG 路徑"""
    if not DESIGNS_CSV.exists():
        print(f"[!] 先跑 count_zero_fact_pdfs.py 產出 _designs.csv")
        sys.exit(1)

    targets = []
    with open(DESIGNS_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            n_img = int(r["n_image_pages"])
            # 有 image-type page 就要走 Vision（text-layer 圖層 callout 抽不到）
            if n_img > 0:
                if args.client and r["client"] != args.client:
                    continue
                targets.append(r)

    print(f"[scan] image-only 0-fact designs: {len(targets)}")
    if args.client:
        print(f"  filter by client: {args.client}")
    if args.limit:
        targets = targets[:args.limit]

    print(f"\n=== 候選清單（給 Claude Read tool 看）===")
    for r in targets:
        print(f"\n[{r['client']}] {r['design_id']} ({r['pdf']})")
        for p in r["image_pages"].split(","):
            if p.strip():
                png = f"{r['client']}_{r['design_id']}_p{p}.png"
                print(f"  Read: {PNG_DIR / png}")

    out_path = ROOT / "outputs" / "zero_fact_pdfs" / "_vision_candidates.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in targets:
            f.write(json.dumps({
                "client": r["client"], "design_id": r["design_id"],
                "pdf": r["pdf"],
                "image_pages": [int(p) for p in r["image_pages"].split(",") if p.strip()],
            }, ensure_ascii=False) + "\n")
    print(f"\n[output] {out_path}")


def cmd_merge(args):
    """驗 vision_facts.jsonl schema → append 進 facts.jsonl"""
    vfile = Path(args.vision_file) if args.vision_file else VISION_FACTS
    if not vfile.exists():
        print(f"[!] vision facts 檔不存在: {vfile}")
        sys.exit(1)

    designs = {}
    for line in open(DESIGNS_JSONL, encoding="utf-8"):
        d = json.loads(line)
        designs[(d["client"], d["design_id"])] = d

    required = ["zone_zh", "l1_code", "design_id", "client", "source_line"]
    n_total = n_valid = n_added = 0
    fixed_facts = []

    for i, line in enumerate(open(vfile, encoding="utf-8")):
        n_total += 1
        try:
            f = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"  [!] line {i+1} JSON error: {e}")
            continue

        missing = [k for k in required if not f.get(k)]
        if missing:
            print(f"  [!] line {i+1} missing: {missing}")
            continue

        client = f["client"]
        design_id = f["design_id"]
        d = designs.get((client, design_id), {})
        f.setdefault("source", "vision")
        f.setdefault("confidence", "vision")
        f.setdefault("eidh", d.get("eidh"))
        f.setdefault("bucket", derive_bucket(d) if d else "UNKNOWN_BOTTOMS")
        f.setdefault("gt_group", derive_gt_group(d) if d else "BOTTOMS")
        f.setdefault("iso", None)
        f.setdefault("combo", None)
        f.setdefault("method", "")

        fixed_facts.append(f)
        n_valid += 1

    print(f"[validate] {n_valid}/{n_total} valid facts")

    if not args.dry_run:
        with open(UNIFIED_FACTS, "a", encoding="utf-8") as fout:
            for f in fixed_facts:
                fout.write(json.dumps(f, ensure_ascii=False) + "\n")
                n_added += 1
        print(f"[append] {n_added} facts → {UNIFIED_FACTS}")
        print(f"[next] 重跑 align/consensus/v7：")
        print(f"  python scripts\\align_to_ie_m7.py")
        print(f"  python scripts\\build_consensus_m7.py")
        print(f"  python scripts\\build_construction_bridge_v7.py")
    else:
        print("[dry-run] 沒寫入 facts.jsonl")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["list", "merge"], required=True)
    p.add_argument("--client", default=None, help="只列特定 client (list mode)")
    p.add_argument("--limit", type=int, default=0, help="最多列幾個 design (list mode)")
    p.add_argument("--vision-file", default=None,
                   help="vision_facts.jsonl 路徑 (merge mode)")
    p.add_argument("--dry-run", action="store_true", help="只驗證不寫入 (merge mode)")
    args = p.parse_args()

    if args.mode == "list":
        cmd_list(args)
    elif args.mode == "merge":
        cmd_merge(args)


if __name__ == "__main__":
    main()
