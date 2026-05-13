"""
validate_bridge_m7.py — 對 PullOn unified/facts.jsonl 驗 8 欄 coverage

不像舊 validate_bridge.py 跑 ONY 1765 筆需要三段式 fallback，
M7 unified/facts.jsonl 已經內建 client + eidh，剩下從 designs.jsonl join。

8 欄 + callout_id surrogate：
  callout_id  surrogate {source}:{design_id}:{l1_code}:{iso}:{seq}
  client      facts.client (內建) → ONY/AF/DICKS/GAP/ATHLETA/...
  fabric      designs.wk → Woven/Knit
  garment_type designs.item → "Pull On Pants"
  item_type   designs.item
  body_type   推 PETITE/TALL/PLUS/MATERNITY/REGULAR (PullOn 預設 REGULAR)
  season      designs.season → "V-HO 2026" 等
  gender      推 program/subgroup（M7 索引沒明標 gender）→ 多半 UNKNOWN
  department  designs.department/category（M7 索引沒明標）

用法：python scripts/validate_bridge_m7.py
"""

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
FACTS = DL / "data" / "ingest" / "unified" / "facts.jsonl"
DESIGNS = DL / "data" / "ingest" / "metadata" / "designs.jsonl"
DIM = DL / "data" / "ingest" / "unified" / "dim.jsonl"

OUT = ROOT / "outputs" / "validate_bridge_m7"
OUT.mkdir(parents=True, exist_ok=True)

# 接 derive_metadata 4 段推導
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from derive_metadata import derive_gender as _derive_gender_v2  # noqa: E402


def derive_body_type(meta: dict) -> str:
    program = (meta.get("program") or "").upper()
    subgroup = (meta.get("subgroup") or "").upper()
    text = f"{program} {subgroup}"
    for tok in ["PETITE", "TALL", "PLUS", "MATERNITY"]:
        if tok in text:
            return tok
    return "REGULAR"


def derive_gender(meta: dict) -> str | None:
    """5 段推導：PDF gender_pdf > PDF brand_division 字眼 > 4 段 derive_metadata"""
    # 段 0: PDF cover 直接寫 gender_pdf（DICKS / ASICS / etc）
    g_pdf = (meta.get("gender_pdf") or "").upper().strip()
    if g_pdf:
        for tok in ["MEN", "WOMEN", "BOY", "GIRL", "KIDS", "BABY"]:
            if tok in g_pdf:
                return tok if tok != "MEN" else ("WOMEN" if "WOMEN" in g_pdf else "MEN")
    # 段 1-4: 4 段推導 (auto + subgroup_token + client_default + manual)
    g = _derive_gender_v2(
        meta.get("client", "") or meta.get("brand_division", ""),
        meta.get("subgroup", "")
    )
    if g != "UNKNOWN":
        return g
    # 段 5: brand_division 含 gender 字（ONY/ATHLETA cover 寫 "OLD NAVY - WOMENS"）
    bd = (meta.get("brand_division") or "").upper()
    if "WOMEN" in bd or "WMNS" in bd:
        return "WOMEN"
    if "MEN" in bd and "WOMEN" not in bd:
        return "MEN"
    if "BOY" in bd:
        return "BOY"
    if "GIRL" in bd:
        return "GIRL"
    if any(t in bd for t in ["BABY", "TODDLER", "INFANT", "NEWBORN"]):
        return "BABY"
    return None


def derive_department(meta: dict) -> str | None:
    return (meta.get("department") or meta.get("category") or "").strip() or None


def main():
    # 1. load designs (key by client+design_id)
    designs = {}
    with open(DESIGNS, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            key = (d.get("client", ""), d.get("design_id", ""))
            designs[key] = d
    print(f"[load] designs: {len(designs)}")

    # 2. iterate facts
    n_total = 0
    n_design_in_meta = 0
    n_field = Counter()
    callout_id_seen = set()
    callout_id_dups = Counter()
    per_design_seq = Counter()

    null_buckets = Counter()  # null reason -> count

    detail_path = OUT / "_quality_report.csv"
    with open(detail_path, "w", newline="", encoding="utf-8-sig") as fout:
        w = csv.writer(fout)
        w.writerow([
            "row_idx", "callout_id", "client", "design_id", "eidh",
            "zone_zh", "l1_code", "iso", "method", "confidence", "source",
            "fabric", "garment_type", "item_type", "body_type", "season",
            "gender", "department",
            "_design_in_meta", "_null_fields",
        ])

        with open(FACTS, encoding="utf-8") as fin:
            for i, line in enumerate(fin):
                fact = json.loads(line)
                n_total += 1

                client = fact.get("client", "")
                design_id = fact.get("design_id", "")
                eidh = fact.get("eidh")
                key = (client, design_id)
                d = designs.get(key, {})
                in_meta = bool(d)
                if in_meta:
                    n_design_in_meta += 1

                # callout_id surrogate
                src_key = (fact.get("source", ""), client, design_id)
                per_design_seq[src_key] += 1
                seq = per_design_seq[src_key]
                callout_id = f'{fact.get("source","")}:{client}:{design_id}:{fact.get("l1_code","")}:{fact.get("iso") or "_"}:{seq}'
                if callout_id in callout_id_seen:
                    callout_id_dups[callout_id] += 1
                callout_id_seen.add(callout_id)

                # 8 欄
                fabric = (d.get("wk") or "").strip().upper() or None
                garment_type = (d.get("item") or "").strip().upper() or None
                item_type = garment_type
                body_type = derive_body_type(d) if d else None
                season = (d.get("season") or "").strip() or None
                gender = derive_gender(d) if d else None
                department = derive_department(d) if d else None

                row_fields = {
                    "callout_id": callout_id,
                    "client": client or None,
                    "fabric": fabric,
                    "garment_type": garment_type,
                    "item_type": item_type,
                    "body_type": body_type,
                    "season": season,
                    "gender": gender,
                    "department": department,
                }
                null_fields = []
                for k, v in row_fields.items():
                    if v:
                        n_field[k] += 1
                    else:
                        null_fields.append(k)
                        null_buckets[k] += 1

                w.writerow([
                    i, callout_id, client, design_id, eidh,
                    fact.get("zone_zh", ""), fact.get("l1_code", ""),
                    fact.get("iso") or "", fact.get("method", ""),
                    fact.get("confidence", ""), fact.get("source", ""),
                    fabric or "", garment_type or "", item_type or "",
                    body_type or "", season or "",
                    gender or "", department or "",
                    "Y" if in_meta else "N",
                    "|".join(null_fields),
                ])

    # 3. summary
    summary_path = OUT / "_summary.csv"
    with open(summary_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["metric", "n", "pct", "note"])
        w.writerow(["facts_total", n_total, "100.0%", ""])
        w.writerow(["design_in_metadata", n_design_in_meta,
                   f"{n_design_in_meta/n_total*100:.1f}%",
                   "facts.(client,design_id) 在 designs.jsonl 找得到"])
        w.writerow(["callout_id_unique",
                    n_total - sum(callout_id_dups.values()),
                    f"{(n_total - sum(callout_id_dups.values()))/n_total*100:.1f}%",
                    f"surrogate 撞號 {sum(callout_id_dups.values())} 筆"])
        w.writerow([])
        w.writerow(["field", "n_filled", "pct", "n_null"])
        for k in ["callout_id", "client", "fabric", "garment_type",
                  "item_type", "body_type", "season", "gender", "department"]:
            filled = n_field[k]
            w.writerow([k, filled, f"{filled/n_total*100:.1f}%", null_buckets[k]])

    # 4. console
    print(f"\n=== M7 PullOn Bridge Validator ===")
    print(f"facts: {n_total}")
    print(f"design in metadata: {n_design_in_meta} ({n_design_in_meta/n_total*100:.1f}%)")
    print(f"callout_id collisions: {sum(callout_id_dups.values())}")
    print("")
    print("[Coverage per field]")
    for k in ["callout_id", "client", "fabric", "garment_type", "item_type", "body_type", "season", "gender", "department"]:
        filled = n_field[k]
        bar = "X" * int(filled / n_total * 30)
        print("  %-14s %4d/%d (%5.1f%%) %s" % (k, filled, n_total, filled/n_total*100, bar))
    print("")
    print("[Reports]")
    print("  " + str(detail_path))
    print("  " + str(summary_path))


if __name__ == "__main__":
    main()
