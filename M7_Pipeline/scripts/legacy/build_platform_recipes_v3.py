"""build_platform_recipes_v3.py — Platform recipes 用 m7_report 五階展開做主源

v2 用 PDF facts (2761 facts / 263 designs)
v3 用 m7_report 五階 (預估 30,000+ steps / 1180 designs)，sample size × 10

Pipeline:
  1. 讀 designs.jsonl → eidh → (design_id, client, subgroup, ...)
  2. 讀 m7_report.jsonl → eidh → 五階 step list
  3. 為每個 EIDH derive (gender, dept, gt, item_type)
  4. 走每個 5lev step：
     - category 中文 → L1 英文 (zone_glossary L1_STANDARD_38)
     - 取 ie_seconds, total_second, method_describe_alt, shape_design
     - bucket key = (gender, dept, gt, item_type, L1)
  5. 跨 EIDH aggregate per bucket → recipe with confidence

輸出：
  outputs/platform/recipes_master_v3.jsonl
  outputs/platform/recipes_master_v3.csv

用法：
  python scripts\\build_platform_recipes_v3.py
"""
from __future__ import annotations
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
DESIGNS = DL / "data" / "ingest" / "metadata" / "designs.jsonl"
M7_REPORT = DL / "data" / "ingest" / "metadata" / "m7_report.jsonl"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"
OUT_DIR = ROOT / "outputs" / "platform"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "scripts"))
from derive_metadata import derive_gender, derive_dept, derive_garment_type  # type: ignore


def to_float(v):
    if v is None:
        return None
    import re
    m = re.search(r'(-?\d+\.?\d*)', str(v).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def load_zh_to_l1():
    g = json.load(open(ZONE_GLOSSARY, encoding="utf-8"))
    l1_std = g.get("L1_STANDARD_38", {})
    return {zh: code for code, zh in l1_std.items()}


def load_designs_by_eidh():
    """eidh → design_meta (client, subgroup, design_id, item, program, wk)
    優先：M7 索引 Excel (1180 全 cover) — fallback designs.jsonl (PullOn 篩過 395)
    """
    by_eidh = {}

    # 1. M7 索引 Excel — 1180 全 cover 的 (eidh, customer, subgroup, item, program, wk)
    M7_INDEX = ROOT / "M7資源索引_M7URL正確版_20260504.xlsx"
    if M7_INDEX.exists():
        try:
            import pandas as pd
            df = None
            for engine in ("calamine", "openpyxl"):
                try:
                    df = pd.read_excel(M7_INDEX, sheet_name="新做工_PullOn", engine=engine)
                    break
                except Exception:
                    continue
            if df is not None:
                for _, row in df.iterrows():
                    if not pd.notna(row.get("Eidh")):
                        continue
                    eidh = str(int(row["Eidh"]))
                    by_eidh[eidh] = {
                        "eidh": int(eidh),
                        "client": str(row.get("客戶", "") or "").strip().upper(),
                        "subgroup": str(row.get("Subgroup", "") or "").strip(),
                        "item": str(row.get("Item", "") or "").strip(),
                        "program": str(row.get("Program", "") or "").strip(),
                        "wk": str(row.get("W/K", "") or "").strip(),
                        "design_id": str(row.get("報價款號", "") or "").strip(),
                        "season": str(row.get("Season", "") or "").strip(),
                    }
                print(f"    [M7 索引] {len(by_eidh)} EIDHs")
        except Exception as e:
            print(f"    [warn] M7 索引讀取失敗: {e}")

    # 2. designs.jsonl 補強（PullOn 篩過版有更精確的 design_id）
    if DESIGNS.exists():
        from_designs = 0
        for line in open(DESIGNS, encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            eidh = d.get("eidh")
            if eidh:
                # 用 designs 蓋過/補強同 eidh 的 metadata
                key = str(eidh)
                if key in by_eidh:
                    # 只蓋過 by_eidh 中為空的欄位
                    for k, v in d.items():
                        if v and not by_eidh[key].get(k):
                            by_eidh[key][k] = v
                else:
                    by_eidh[key] = d
                from_designs += 1
        print(f"    [designs.jsonl] +{from_designs} entries (合併後 {len(by_eidh)})")

    return by_eidh


def main():
    print("[1] Load zone_glossary ZH→L1 mapping")
    zh_to_l1 = load_zh_to_l1()
    print(f"    {len(zh_to_l1)} 中文 zone names → L1 code")

    print("[2] Load designs.jsonl (EIDH metadata)")
    designs_by_eidh = load_designs_by_eidh()
    print(f"    {len(designs_by_eidh)} EIDHs in designs.jsonl")

    print("[3] Walk m7_report.jsonl → 5lev steps")
    if not M7_REPORT.exists():
        print(f"[!] {M7_REPORT} not found")
        sys.exit(1)

    # bucket key = (gender, dept, gt, item_type, l1)
    buckets = defaultdict(lambda: {
        "n_steps": 0,
        "n_eidhs": set(),
        "n_clients": set(),
        "ie_seconds": [],
        "total_seconds": [],
        "method_codes": Counter(),
        "method_describe_alts": Counter(),
        "shape_designs": Counter(),
        "categories_zh": Counter(),
        "parts_zh": Counter(),
    })

    skipped_no_meta = 0
    skipped_no_l1 = 0
    n_eidh_processed = 0
    n_steps_total = 0

    for line in open(M7_REPORT, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        eidh = str(r.get("eidh", ""))
        if not eidh:
            continue

        # derive design metadata
        d = designs_by_eidh.get(eidh)
        if not d:
            # 用 m7_report 自帶的 customer / item 嘗試 derive
            client = (r.get("customer") or "").upper().split("(")[0].strip()
            subgroup = ""  # m7_report 沒有 subgroup
            item = r.get("item", "") or ""
            program = ""
            wk = r.get("wk", "")
        else:
            client = (d.get("client") or "").upper()
            subgroup = d.get("subgroup", "") or ""
            item = d.get("item") or r.get("item", "") or ""
            program = d.get("program", "") or ""
            wk = d.get("wk") or r.get("wk", "")

        gender = derive_gender(client, subgroup) or "UNKNOWN"
        dept = derive_dept(client, program, subgroup) or "UNKNOWN"
        gt = derive_garment_type(item) or "UNKNOWN"
        # item_type: PullOn pipeline 全是 PANTS-family；用 wk (Knit/Woven) 細分
        item_type = (wk or "").upper() if wk else gt

        if gender == "UNKNOWN" and dept == "UNKNOWN":
            skipped_no_meta += 1
            continue

        n_eidh_processed += 1
        steps = r.get("five_level_detail", [])
        for step in steps:
            cat_zh = (step.get("category") or "").strip()
            l1 = zh_to_l1.get(cat_zh)
            if not l1:
                skipped_no_l1 += 1
                continue
            n_steps_total += 1

            key = (gender, dept, gt, item_type, l1)
            b = buckets[key]
            b["n_steps"] += 1
            b["n_eidhs"].add(eidh)
            b["n_clients"].add(client)

            ie_sec = to_float(step.get("ie_seconds"))
            tot_sec = to_float(step.get("total_second"))
            if ie_sec is not None:
                b["ie_seconds"].append(ie_sec)
            if tot_sec is not None:
                b["total_seconds"].append(tot_sec)

            mc = (step.get("method_code") or "").strip()
            mda = (step.get("method_describe_alt") or "").strip()
            sd = (step.get("shape_design") or "").strip()
            part = (step.get("part") or "").strip()
            if mc and not mc.startswith("new_method_describe_"):
                b["method_codes"][mc] += 1
            if mda:
                b["method_describe_alts"][mda] += 1
            if sd:
                b["shape_designs"][sd] += 1
            b["categories_zh"][cat_zh] += 1
            if part:
                b["parts_zh"][part] += 1

    print(f"    {n_eidh_processed} EIDH processed (skipped {skipped_no_meta} no_meta)")
    print(f"    {n_steps_total} steps captured (skipped {skipped_no_l1} no L1 mapping)")
    print(f"    {len(buckets)} unique 5-dim keys")

    print("\n[4] Aggregate per bucket → recipe")
    recipes = []
    for key, b in buckets.items():
        gender, dept, gt, item_type, l1 = key
        n_steps = b["n_steps"]
        n_eidhs = len(b["n_eidhs"])
        n_clients = len(b["n_clients"])
        # confidence
        if n_steps >= 30 and n_clients >= 3:
            conf = "high"
        elif n_steps >= 10 and n_clients >= 2:
            conf = "medium"
        elif n_steps >= 5:
            conf = "low"
        else:
            conf = "very_low"

        ies = b["ie_seconds"]
        tots = b["total_seconds"]
        recipe = {
            "key": {
                "gender": gender,
                "dept": dept,
                "gt": gt,
                "item_type": item_type,
                "l1": l1,
            },
            "category_zh": b["categories_zh"].most_common(1)[0][0] if b["categories_zh"] else "",
            "top_parts": [{"name": n, "count": c} for n, c in b["parts_zh"].most_common(5)],
            "n_steps": n_steps,
            "n_eidhs": n_eidhs,
            "n_clients": n_clients,
            "confidence": conf,
            "ie_avg_seconds": round(mean(ies), 3) if ies else None,
            "ie_median_seconds": round(median(ies), 3) if ies else None,
            "ie_min_seconds": round(min(ies), 3) if ies else None,
            "ie_max_seconds": round(max(ies), 3) if ies else None,
            "total_avg_seconds": round(mean(tots), 1) if tots else None,
            "top_method_codes": [{"code": c, "n": n} for c, n in b["method_codes"].most_common(5)],
            "top_method_describes": [{"text": t[:200], "n": n} for t, n in b["method_describe_alts"].most_common(5)],
            "top_shape_designs": [{"shape": s, "n": n} for s, n in b["shape_designs"].most_common(5)],
            "source": "m7_report_v3_5lev_consensus",
        }
        recipes.append(recipe)

    # sort by n_steps desc
    recipes.sort(key=lambda r: -r["n_steps"])

    # write JSONL
    out_jsonl = OUT_DIR / "recipes_master_v3.jsonl"
    out_csv = OUT_DIR / "recipes_master_v3.csv"
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for r in recipes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # write CSV
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["gender", "dept", "gt", "item_type", "l1", "category_zh",
                    "n_steps", "n_eidhs", "n_clients", "confidence",
                    "ie_avg_sec", "ie_median_sec",
                    "top_part", "top_method_code",
                    "top_method_describe", "top_shape_design"])
        for r in recipes:
            k = r["key"]
            w.writerow([
                k["gender"], k["dept"], k["gt"], k["item_type"], k["l1"],
                r["category_zh"],
                r["n_steps"], r["n_eidhs"], r["n_clients"], r["confidence"],
                r["ie_avg_seconds"] or "",
                r["ie_median_seconds"] or "",
                r["top_parts"][0]["name"] if r["top_parts"] else "",
                r["top_method_codes"][0]["code"] if r["top_method_codes"] else "",
                (r["top_method_describes"][0]["text"][:80] if r["top_method_describes"] else ""),
                r["top_shape_designs"][0]["shape"] if r["top_shape_designs"] else "",
            ])

    # summary
    print(f"\n=== recipes_master_v3 summary ===")
    print(f"  total recipes:      {len(recipes)}")
    conf_dist = Counter(r["confidence"] for r in recipes)
    for c in ("high", "medium", "low", "very_low"):
        print(f"  {c:10}:         {conf_dist.get(c, 0)}")
    print(f"\n[output]")
    print(f"  {out_jsonl}")
    print(f"  {out_csv}")


if __name__ == "__main__":
    main()
