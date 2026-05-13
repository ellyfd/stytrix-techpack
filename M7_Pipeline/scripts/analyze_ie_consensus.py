"""
analyze_ie_consensus.py — 純 IE 五階 ground truth 共識分析

不需要 PDF/PPTX，直接讀 1180 csv_5level/*.csv + M7 索引 join → 算共識：
  group by (bucket, L1_code) → 跨 EIDH consensus
    每組算：
      - n_eidh / n_clients
      - typical L4 (most common)
      - typical machine
      - avg_seconds / median_seconds
      - L4 distribution (top 5)
      - machine distribution (top 5)
      - by_client breakdown (此 zone 在每客戶的工序變化)

輸出：
  m7_organized_v2/aligned/ie_consensus.jsonl
  m7_organized_v2/aligned/ie_consensus_summary.csv

用法：python scripts/analyze_ie_consensus.py
"""

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV5_DIR = ROOT / "m7_organized_v2" / "csv_5level"
ALIGNED_DIR = ROOT / "m7_organized_v2" / "aligned"

sys.path.insert(0, str(ROOT / "scripts"))
from m7_constants import ZH_TO_L1, normalize_client, derive_bucket  # noqa: E402
from m7_eidh_loader import load_m7_index  # noqa: E402


def load_index():
    """讀 M7 索引：eidh → {client, wk, item, ...}（用共用 helper，套 ITEM_FILTER）"""
    df = load_m7_index()
    out = {}
    for _, row in df.iterrows():
        if pd.isna(row["Eidh"]):
            continue
        eidh = int(row["Eidh"])
        out[eidh] = {
            "client": normalize_client(str(row.get("客戶") or "")),
            "wk": str(row.get("W/K") or ""),
            "item": str(row.get("Item") or ""),
            "program": str(row.get("Program") or ""),
            "subgroup": str(row.get("Subgroup") or ""),
            "design_id": str(row.get("報價款號") or ""),
        }
    return out


def main():
    if not CSV5_DIR.exists():
        print(f"[!] csv_5level 不存在: {CSV5_DIR}", file=sys.stderr)
        sys.exit(1)

    ALIGNED_DIR.mkdir(parents=True, exist_ok=True)
    eidh_meta = load_index()
    print(f"[load] M7 索引: {len(eidh_meta)} EIDH")

    # group by (bucket, l1_code)
    groups = defaultdict(lambda: {
        "eidhs": set(), "clients": set(), "designs": set(),
        "l4": Counter(), "machine": Counter(),
        "l2": Counter(), "l3": Counter(), "l5": Counter(),
        "seconds": [], "n_steps": 0,
        "by_client": defaultdict(lambda: {"l4": Counter(), "machine": Counter(),
                                          "seconds": [], "n_steps": 0}),
    })

    n_csv = 0
    n_no_meta = 0
    for f in sorted(CSV5_DIR.glob("*.csv")):
        try:
            eidh = int(f.stem.split("_")[0])
        except (ValueError, IndexError):
            continue
        n_csv += 1
        meta = eidh_meta.get(eidh)
        if not meta:
            n_no_meta += 1
            continue
        bucket = derive_bucket(meta)
        client = meta["client"]
        design_id = meta["design_id"]

        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            cat = (row.get("category") or "").strip()
            l1 = ZH_TO_L1.get(cat)
            if not l1:
                continue
            l2 = (row.get("part") or "").strip()
            l3 = (row.get("Shape_Design") or "").strip()
            l4 = (row.get("Method_Describe") or "").strip()
            l5 = (row.get("section") or "").strip()
            mach = (row.get("machine_name") or "").strip()
            try:
                sec = float(row.get("total_second", 0) or 0)
            except (TypeError, ValueError):
                sec = 0.0

            gkey = (bucket, l1)
            g = groups[gkey]
            g["eidhs"].add(eidh)
            g["clients"].add(client)
            g["designs"].add(design_id)
            g["n_steps"] += 1
            if l2: g["l2"][l2] += 1
            if l3: g["l3"][l3] += 1
            if l4: g["l4"][l4] += 1
            if l5: g["l5"][l5] += 1
            if mach: g["machine"][mach] += 1
            if sec > 0: g["seconds"].append(sec)

            bc = g["by_client"][client]
            bc["n_steps"] += 1
            if l4: bc["l4"][l4] += 1
            if mach: bc["machine"][mach] += 1
            if sec > 0: bc["seconds"].append(sec)

    print(f"[load] {n_csv} CSV, {n_no_meta} 沒在 M7 索引")
    print(f"[group] {len(groups)} (bucket, l1) 組合")

    # 寫 jsonl
    out_jsonl = ALIGNED_DIR / "ie_consensus.jsonl"
    out_csv = ALIGNED_DIR / "ie_consensus_summary.csv"
    entries = []
    for (bucket, l1), g in sorted(groups.items()):
        n_eidh = len(g["eidhs"])
        n_clients = len(g["clients"])
        n_designs = len(g["designs"])

        def top_dist(c, top=5):
            if not c:
                return []
            tot = sum(c.values())
            return [{"name": k, "n": n, "pct": round(n/tot*100, 1)}
                    for k, n in c.most_common(top)]

        avg_sec = round(mean(g["seconds"]), 2) if g["seconds"] else None
        med_sec = round(median(g["seconds"]), 2) if g["seconds"] else None

        # by_client breakdown
        client_dist = {}
        for c, bc in g["by_client"].items():
            client_dist[c] = {
                "n_steps": bc["n_steps"],
                "top_l4": bc["l4"].most_common(1)[0][0] if bc["l4"] else None,
                "top_machine": bc["machine"].most_common(1)[0][0] if bc["machine"] else None,
                "avg_seconds": round(mean(bc["seconds"]), 2) if bc["seconds"] else None,
            }

        entry = {
            "key": {"bucket": bucket, "l1": l1},
            "n_steps": g["n_steps"],
            "n_eidh": n_eidh,
            "n_clients": n_clients,
            "n_designs": n_designs,
            "avg_seconds": avg_sec,
            "median_seconds": med_sec,
            "l2_dist": top_dist(g["l2"]),
            "l3_dist": top_dist(g["l3"]),
            "l4_dist": top_dist(g["l4"]),
            "l5_dist": top_dist(g["l5"]),
            "machine_dist": top_dist(g["machine"]),
            "typical_l4": g["l4"].most_common(1)[0][0] if g["l4"] else None,
            "typical_machine": g["machine"].most_common(1)[0][0] if g["machine"] else None,
            "by_client": client_dist,
        }
        entries.append(entry)

    with open(out_jsonl, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # csv 人類好讀
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["bucket", "l1_code", "n_steps", "n_eidh", "n_clients",
                    "avg_sec", "median_sec",
                    "typical_l4", "typical_machine",
                    "l4_top3", "machine_top3", "client_list"])
        for e in sorted(entries, key=lambda x: -x["n_steps"]):
            l4_top3 = " | ".join(f'{d["name"][:30]}({d["n"]})' for d in e["l4_dist"][:3])
            mach_top3 = " | ".join(f'{d["name"][:20]}({d["n"]})' for d in e["machine_dist"][:3])
            w.writerow([
                e["key"]["bucket"], e["key"]["l1"],
                e["n_steps"], e["n_eidh"], e["n_clients"],
                e["avg_seconds"] or "", e["median_seconds"] or "",
                (e["typical_l4"] or "")[:50], (e["typical_machine"] or "")[:30],
                l4_top3, mach_top3,
                ",".join(sorted(e["by_client"].keys())),
            ])

    # console summary
    print(f"\n=== IE Consensus summary ===")
    print(f"  total entries: {len(entries)}")
    print(f"  total steps:   {sum(e['n_steps'] for e in entries)}")
    print(f"  total eidh:    {n_csv}")

    print(f"\n[Top 15 (bucket × L1) by step count]")
    print(f"  {'bucket':14s} L1   {'n_steps':>7s} {'n_eidh':>6s} {'cli':>3s}  "
          f"{'avg_s':>5s} {'med_s':>5s}  {'typical_L4':<28s}  {'machine':<22s}")
    for e in sorted(entries, key=lambda x: -x["n_steps"])[:15]:
        l4 = (e["typical_l4"] or "-")[:28]
        m = (e["typical_machine"] or "-")[:22]
        avg = f"{e['avg_seconds']:.0f}" if e["avg_seconds"] else "-"
        med = f"{e['median_seconds']:.0f}" if e["median_seconds"] else "-"
        print(f"  {e['key']['bucket']:14s} {e['key']['l1']:3s}  "
              f"{e['n_steps']:>7d} {e['n_eidh']:>6d} {e['n_clients']:>3d}  "
              f"{avg:>5s} {med:>5s}  {l4:<28s}  {m:<22s}")

    print(f"\n[Output]")
    print(f"  {out_jsonl}")
    print(f"  {out_csv}")


if __name__ == "__main__":
    main()
