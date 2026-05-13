"""build_construction_bridge_v7.py — 部位 mapping 做工 deliverable

合併三個來源：
  1. construction_bridge_v6.json   (legacy: GT × zone callout consensus)
  2. consensus_m7.jsonl            (M7 PullOn: bucket × L1 callout consensus)
  3. ie_consensus.jsonl            (IE 五階 production reality)

輸出：
  outputs/construction_bridge_v7.json     (完整 JSON)
  outputs/construction_bridge_v7_flat.csv (人類可讀 CSV)

用法：python scripts/build_construction_bridge_v7.py
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
ALIGNED = ROOT / "m7_organized_v2" / "aligned"
OUR = ALIGNED / "consensus_m7.jsonl"
IE = ALIGNED / "ie_consensus.jsonl"
V6 = DL / "General Model_Path2_Construction Suggestion" / "iso_lookup_factory_v4.3.json"
# v6.1 在 uploads，但 user 也可能放別的位置；fallback 找
V6_CANDIDATES = [
    ROOT.parent / "uploads" / "construction_bridge_v6.json",
    DL / "data" / "ingest" / "construction_bridge_v6.json",
    ROOT / "construction_bridge_v6.json",
]
OUT_DIR = ROOT / "outputs" / "bridge_v7"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ISO → ZH 縫紉機種關鍵字（跟 validate_ie_consistency 同步）
ISO_TO_IE_KEYWORDS = {
    "103": ["暗縫"], "301": ["平車", "鎖式"], "304": ["人字"],
    "401": ["鎖鏈", "單針鎖鏈"], "406": ["三本", "二針三線", "覆蓋"],
    "504": ["三線拷克"], "514": ["四線拷克"], "516": ["五線拷克"],
    "602": ["二針四線", "兩針四線", "爬網"],
    "605": ["三針五線", "拼縫車-三針五線", "爬網", "扒網"],
    "607": ["四針六線", "拼縫", "併縫", "倂縫"],
}
IE_NON_SEWING = ["手工", "燙工", "手燙", "做記號", "翻修", "打結車", "釘釦", "鎖眼"]


def compute_gap_flag(our_iso, ie_machine_dist):
    """gap 判斷：
       align — our_iso 在 IE typical_machine（最高頻、且非手工/燙工）對應 keyword 中
       gap_layered — our_iso 在 IE machine_dist top 3 任一機種命中
       gap_real — 完全不在
    """
    if not our_iso or not ie_machine_dist:
        return "no_data"
    keywords = ISO_TO_IE_KEYWORDS.get(our_iso, [])
    if not keywords:
        return "no_iso_mapping"
    # 取真縫紉機種列表
    real_machines = [m for m in ie_machine_dist
                     if not any(kw in m.get("name", "") for kw in IE_NON_SEWING)]
    if not real_machines:
        return "no_data"
    top1 = real_machines[0].get("name", "")
    if any(kw in top1 for kw in keywords):
        return "align"
    for m in real_machines[1:3]:
        if any(kw in m.get("name", "") for kw in keywords):
            return "gap_layered"
    return "gap_real"


def main():
    # 1. Load IE consensus (key by (bucket, L1))
    ie_idx = {}
    for line in open(IE, encoding="utf-8"):
        e = json.loads(line)
        ie_idx[(e["key"]["bucket"], e["key"]["l1"])] = e
    print(f"[load] IE consensus: {len(ie_idx)} entries")

    # 2. Load our consensus
    our_entries = [json.loads(l) for l in open(OUR, encoding="utf-8")]
    print(f"[load] our consensus (M7 PullOn): {len(our_entries)} entries")

    # 3. Load v6 legacy (optional — for keeping non-PANTS GTs)
    v6 = None
    for cand in V6_CANDIDATES:
        if cand.exists():
            v6 = json.loads(cand.read_text(encoding="utf-8"))
            print(f"[load] v6 legacy: {cand}")
            break
    if not v6:
        print(f"[skip] v6 legacy not found, building bottoms-only bridge")

    # 4. Build v7
    bridges = {}
    flat_rows = []

    # 4a. M7 PullOn (bucket × L1) — main payload
    for o in our_entries:
        bucket = o["key"]["bucket"]
        l1 = o["key"]["l1"]
        ie = ie_idx.get((bucket, l1))
        flag = compute_gap_flag(o.get("top_iso"), ie.get("machine_dist", []) if ie else [])
        # 真縫紉機種 top1（過濾手工/燙工）— 給顯示用
        ie_real_top1 = ""
        if ie:
            real = [m for m in ie.get("machine_dist", [])
                    if not any(k in m.get("name", "") for k in IE_NON_SEWING)]
            if real:
                ie_real_top1 = real[0].get("name", "")

        zone_zh = ""
        # 從 typical_recipe 或 method 名找對應中文（簡化：跟 KW_TO_L1_BOTTOMS 對照）
        L1_TO_ZH = {"WB": "腰頭", "PK": "口袋", "LO": "褲口", "PS": "褲合身",
                    "RS": "褲襠", "SS": "脅邊", "PL": "門襟", "DC": "繩類",
                    "BM": "下襬", "PD": "褶", "SB": "剪接線_下身類", "SR": "裙合身",
                    "ZP": "拉鍊", "LB": "商標", "LI": "裡布"}
        zone_zh = L1_TO_ZH.get(l1, l1)

        entry = {
            "l1_code": l1,
            "zone_zh": zone_zh,
            "n_callouts": o.get("n_total", 0),
            "n_designs": o.get("n_designs", 0),
            "n_clients": o.get("n_clients", 0),
            "design_intent": {
                "top_iso": o.get("top_iso"),
                "top_method": o.get("top_method"),
                "method_dist": o.get("methods", [])[:5],
                "iso_dist": o.get("iso_distribution", [])[:5],
            },
            "production_reality": {
                "typical_machine": ie.get("typical_machine") if ie else None,
                "machine_dist_real": [m for m in (ie.get("machine_dist", []) if ie else [])
                                       if not any(k in m.get("name", "") for k in IE_NON_SEWING)][:3],
                "typical_l4": ie.get("typical_l4") if ie else None,
                "n_steps": ie.get("n_steps") if ie else 0,
                "avg_seconds": ie.get("avg_seconds") if ie else None,
            } if ie else None,
            "alignment": {
                "flag": flag,
                "design_iso": o.get("top_iso"),
                "ie_top1_machine": (ie.get("typical_machine") if ie else None),
            },
            "typical_recipe": o.get("typical_recipe"),
            "confidence": o.get("confidence", "unknown"),
            "client_ids": o.get("client_ids", [])[:10],
        }
        bridges.setdefault(bucket, {"zones": {}})["zones"][zone_zh] = entry

        flat_rows.append({
            "bucket": bucket, "l1_code": l1, "zone_zh": zone_zh,
            "n_callouts": entry["n_callouts"], "n_designs": entry["n_designs"],
            "n_clients": entry["n_clients"],
            "design_iso": o.get("top_iso") or "",
            "design_method": o.get("top_method") or "",
            "production_machine": ie_real_top1 or (ie.get("typical_machine") if ie else "") or "",
            "production_machine_typical": (ie.get("typical_machine") if ie else "") or "",
            "production_l4": (ie.get("typical_l4") if ie else "") or "",
            "production_avg_sec": (ie.get("avg_seconds") if ie else "") or "",
            "gap_flag": flag,
            "confidence": o.get("confidence", ""),
        })

    # 4b. Legacy v6 GTs (TOP / DRESS / OUTERWEAR / SET / UNKNOWN) — pass through
    legacy_kept = []
    if v6 and "bridges" in v6:
        for gt, gt_data in v6["bridges"].items():
            if gt in ("PANTS",):  # PANTS 已被 bucket 取代
                continue
            bridges[gt] = {"zones": {}, "_source": "v6.1_legacy"}
            for zone, zd in gt_data.get("zones", {}).items():
                bridges[gt]["zones"][zone] = {
                    "count": zd.get("count", 0),
                    "method_dist_legacy": zd.get("methods", {}),
                    "iso_dist_legacy": zd.get("iso_codes", {}),
                    "_note": "v6.1 callout-only, no IE join, no bucket split",
                }
            legacy_kept.append(gt)
        print(f"[merge] kept v6 legacy GTs: {legacy_kept}")

    # 5. Write JSON
    out_json = OUT_DIR / "construction_bridge_v7.json"
    payload = {
        "version": "v7.0",
        "method": "v6.1 callout-consensus + ie_consensus join + bucket(WK)×L1 PK + gap_flag",
        "stats": {
            "n_bucket_l1_entries": len(our_entries),
            "n_legacy_gts": len(legacy_kept),
            "buckets": sorted(set(o["key"]["bucket"] for o in our_entries)),
        },
        "bridges": bridges,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 6. Write flat CSV
    out_csv = OUT_DIR / "construction_bridge_v7_flat.csv"
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["bucket", "l1_code", "zone_zh",
                                           "n_callouts", "n_designs", "n_clients",
                                           "design_iso", "design_method",
                                           "production_machine", "production_machine_typical",
                                           "production_l4", "production_avg_sec",
                                           "gap_flag", "confidence"])
        w.writeheader()
        for r in sorted(flat_rows, key=lambda x: (x["bucket"], -x["n_callouts"])):
            w.writerow(r)

    # 7. Console summary
    print(f"\n=== construction_bridge_v7 ===")
    print(f"  M7 entries:     {len(our_entries)} (bucket × L1)")
    print(f"  Legacy GTs:     {len(legacy_kept)}")
    print(f"  Total bridges:  {len(bridges)}")

    flag_counts = {"align": 0, "gap_layered": 0, "gap_real": 0, "no_data": 0, "no_iso_mapping": 0}
    for r in flat_rows:
        flag_counts[r["gap_flag"]] = flag_counts.get(r["gap_flag"], 0) + 1
    print(f"\n[Gap flag 分布]")
    for k, v in flag_counts.items():
        print(f"  {k:18s} {v}")

    print(f"\n[gap_real 真衝突清單（顯示 IE 真縫紉機種，非手工）]")
    for r in flat_rows:
        if r["gap_flag"] == "gap_real":
            prod = r["production_machine"] or r["production_machine_typical"]
            print(f"  {r['bucket']:14s} {r['l1_code']:3s} ({r['zone_zh']:6s})  "
                  f"design={r['design_iso']} → prod_real={prod[:20]}")

    print(f"\n[Output]")
    print(f"  {out_json}")
    print(f"  {out_csv}")


if __name__ == "__main__":
    main()
