"""build_platform_recipes_v4.py — Platform recipes 整合 m7 5lev + SSRS 細工段

v3：用 m7_report.jsonl 五階展開（14,996 step / 302 recipes / 72 high）
v4：再 JOIN m7_detail.csv 細工段（預估 70K rows / EIDH × 60 sub-op）
    每個 5lev step 拆成 N 個 sub-operation，含真實機種 / Skill_Level / 秒值

JOIN key:
  m7_report 的 (eidh, category, part, shape_design, method_describe)
  ↔ m7_detail 的 (_eidh, category, part, Shape_Design, Method_Describe)

輸出每個 recipe 帶：
  - typical_machines (top by frequency)
  - typical_skill_levels (E最容易 → A最難)
  - typical_sub_operations (top section by name + IE 秒值)
  - cumulative IE breakdown by skill level / machine

用法：
  python scripts\\build_platform_recipes_v4.py
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
M7_DETAIL = DL / "data" / "ingest" / "metadata" / "m7_detail.csv"
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
    """eidh → design_meta，優先 M7 索引 Excel (1180 cover) + designs.jsonl 補強"""
    by_eidh = {}
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
        except Exception:
            pass

    if DESIGNS.exists():
        for line in open(DESIGNS, encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            eidh = d.get("eidh")
            if eidh:
                key = str(eidh)
                if key in by_eidh:
                    for k, v in d.items():
                        if v and not by_eidh[key].get(k):
                            by_eidh[key][k] = v
                else:
                    by_eidh[key] = d
    return by_eidh


def load_m7_detail_index():
    """m7_detail.csv → {(eidh, category, part, shape, method): [sub_ops]}"""
    if not M7_DETAIL.exists():
        print(f"[!] {M7_DETAIL} 不存在 — 先跑 fetch_m7_detail.py")
        return {}
    idx = defaultdict(list)
    n_rows = 0
    with open(M7_DETAIL, encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            n_rows += 1
            eidh = (row.get("_eidh") or "").strip()
            cat = (row.get("category") or "").strip()
            part = (row.get("part") or "").strip()
            shape = (row.get("Shape_Design") or "").strip()
            method = (row.get("Method_Describe") or "").strip()
            key = (eidh, cat, part, shape, method)
            idx[key].append({
                "section": (row.get("section") or "").strip(),
                "machine_name": (row.get("machine_name") or "").strip(),
                "skill_level": (row.get("Skill_Level") or "").strip(),
                "sewing_process": (row.get("Sewing_Process") or "").strip(),
                "size": (row.get("size") or "").strip(),
                "total_second": to_float(row.get("total_second")),
            })
    print(f"[load] m7_detail.csv: {n_rows:,} rows → {len(idx)} unique 5lev keys")
    return idx


def main():
    print("[1] zone_glossary ZH→L1 mapping")
    zh_to_l1 = load_zh_to_l1()
    print(f"    {len(zh_to_l1)} 中文 zone names → L1 code")

    print("[2] designs.jsonl (EIDH metadata)")
    designs = load_designs_by_eidh()
    print(f"    {len(designs)} EIDHs")

    print("[3] m7_detail.csv (sub-operations)")
    detail_idx = load_m7_detail_index()

    print("[4] Walk m7_report.jsonl + JOIN m7_detail")
    if not M7_REPORT.exists():
        print(f"[!] {M7_REPORT} not found")
        sys.exit(1)

    buckets = defaultdict(lambda: {
        "n_steps": 0,
        "n_subops": 0,
        "n_eidhs": set(),
        "n_clients": set(),
        "ie_seconds_step": [],
        "machines": Counter(),
        "skill_levels": Counter(),
        "sections": Counter(),
        "method_codes": Counter(),
        "method_describes": Counter(),
        "shape_designs": Counter(),
        "categories_zh": Counter(),
        "parts_zh": Counter(),
        # 細粒度：每個 sub-op 的 (machine, skill, section, total_sec)
        "subop_records": [],  # for further analysis if needed
    })

    skipped_no_meta = 0
    skipped_no_l1 = 0
    n_eidh_processed = 0
    n_steps_total = 0
    n_steps_with_detail = 0

    for line in open(M7_REPORT, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        eidh = str(r.get("eidh", ""))
        if not eidh:
            continue

        d = designs.get(eidh)
        if not d:
            client = (r.get("customer") or "").upper().split("(")[0].strip()
            subgroup = ""
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
            if ie_sec is not None:
                b["ie_seconds_step"].append(ie_sec)

            mc = (step.get("method_code") or "").strip()
            mda = (step.get("method_describe_alt") or "").strip()
            sd = (step.get("shape_design") or "").strip()
            part = (step.get("part") or "").strip()
            md = (step.get("method_describe") or "").strip()
            if mc and not mc.startswith("new_method_describe_"):
                b["method_codes"][mc] += 1
            if mda:
                b["method_describes"][mda] += 1
            if sd:
                b["shape_designs"][sd] += 1
            b["categories_zh"][cat_zh] += 1
            if part:
                b["parts_zh"][part] += 1

            # JOIN 細工段 sub-ops
            # m7_detail 的 Method_Describe 其實對應 m7_report 的 method_code（不是 method_describe）
            join_key = (eidh, cat_zh, part, sd, mc)
            sub_ops = detail_idx.get(join_key, [])
            if sub_ops:
                n_steps_with_detail += 1
            for op in sub_ops:
                b["n_subops"] += 1
                if op["machine_name"]:
                    b["machines"][op["machine_name"]] += 1
                if op["skill_level"]:
                    b["skill_levels"][op["skill_level"]] += 1
                if op["section"]:
                    b["sections"][op["section"]] += 1
                # 簡化 record
                b["subop_records"].append({
                    "machine": op["machine_name"],
                    "skill": op["skill_level"],
                    "section": op["section"],
                    "sec": op["total_second"],
                })

    print(f"\n    {n_eidh_processed} EIDH processed (skipped {skipped_no_meta} no_meta)")
    print(f"    {n_steps_total:,} steps captured (skipped {skipped_no_l1} no L1 mapping)")
    print(f"    {n_steps_with_detail:,} steps matched to m7_detail sub-ops ({n_steps_with_detail/max(n_steps_total,1)*100:.1f}%)")
    print(f"    {len(buckets)} unique 5-dim keys")

    print("\n[5] Aggregate per bucket → recipe v4")
    recipes = []
    for key, b in buckets.items():
        gender, dept, gt, item_type, l1 = key
        n_steps = b["n_steps"]
        n_eidhs = len(b["n_eidhs"])
        n_clients = len(b["n_clients"])
        if n_steps >= 30 and n_clients >= 3:
            conf = "high"
        elif n_steps >= 10 and n_clients >= 2:
            conf = "medium"
        elif n_steps >= 5:
            conf = "low"
        else:
            conf = "very_low"

        ies = b["ie_seconds_step"]
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
            "n_subops": b["n_subops"],
            "n_eidhs": n_eidhs,
            "n_clients": n_clients,
            "confidence": conf,
            "ie_avg_sec_per_step": round(mean(ies), 3) if ies else None,
            "ie_median_sec_per_step": round(median(ies), 3) if ies else None,
            "top_method_codes": [{"code": c, "n": n} for c, n in b["method_codes"].most_common(5)],
            "top_method_describes": [{"text": t[:200], "n": n} for t, n in b["method_describes"].most_common(5)],
            "top_shape_designs": [{"shape": s, "n": n} for s, n in b["shape_designs"].most_common(5)],
            "top_machines": [{"name": m, "n": n} for m, n in b["machines"].most_common(5)],
            "top_skill_levels": [{"level": s, "n": n} for s, n in b["skill_levels"].most_common(5)],
            "top_sections": [{"section": s, "n": n} for s, n in b["sections"].most_common(10)],
            "source": "m7_v4_5lev_plus_subop_detail",
        }
        recipes.append(recipe)

    recipes.sort(key=lambda r: -r["n_steps"])

    # write JSONL
    out_jsonl = OUT_DIR / "recipes_master_v4.jsonl"
    out_csv = OUT_DIR / "recipes_master_v4.csv"
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for r in recipes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # write CSV
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["gender", "dept", "gt", "item_type", "l1", "category_zh",
                    "n_steps", "n_subops", "n_eidhs", "n_clients", "confidence",
                    "ie_avg_sec", "ie_median_sec",
                    "top_part", "top_method_code",
                    "top_method_describe", "top_shape",
                    "top_machine", "top_skill", "top_section"])
        for r in recipes:
            k = r["key"]
            w.writerow([
                k["gender"], k["dept"], k["gt"], k["item_type"], k["l1"],
                r["category_zh"],
                r["n_steps"], r["n_subops"], r["n_eidhs"], r["n_clients"], r["confidence"],
                r["ie_avg_sec_per_step"] or "",
                r["ie_median_sec_per_step"] or "",
                r["top_parts"][0]["name"] if r["top_parts"] else "",
                r["top_method_codes"][0]["code"] if r["top_method_codes"] else "",
                (r["top_method_describes"][0]["text"][:80] if r["top_method_describes"] else ""),
                r["top_shape_designs"][0]["shape"] if r["top_shape_designs"] else "",
                r["top_machines"][0]["name"][:40] if r["top_machines"] else "",
                r["top_skill_levels"][0]["level"] if r["top_skill_levels"] else "",
                r["top_sections"][0]["section"] if r["top_sections"] else "",
            ])

    # summary
    print(f"\n=== recipes_master_v4 summary ===")
    print(f"  total recipes:    {len(recipes)}")
    conf_dist = Counter(r["confidence"] for r in recipes)
    for c in ("high", "medium", "low", "very_low"):
        print(f"  {c:10}:       {conf_dist.get(c, 0)}")
    print(f"\n[output]")
    print(f"  {out_jsonl}")
    print(f"  {out_csv}")


if __name__ == "__main__":
    main()
