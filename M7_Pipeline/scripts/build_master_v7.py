"""build_master_v7.py — Single Master 整合版（取代 v6 + by_client）

把 m7_report.jsonl + m7_detail.csv + facts.jsonl 整合成單一 master.jsonl。
每筆 entry 同時含：
  - 5-dim key (gender/dept/gt/it/l1) + fabric (top-level)
  - iso_distribution / methods / client_distribution（給 platform 通用模型 view A 用）
  - by_client[brand][knit/woven][L2-L5 + IE 秒值]（給聚陽模型 view B 用）
  - design_ids / embedding_text / confidence

Output: outputs/master.jsonl

⛔ 範圍：只做做工 pipeline，尺寸表 pom_rules/* 完全不碰。

跑：python scripts\\build_master_v7.py
"""
from __future__ import annotations
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from m7_eidh_loader import load_m7_index  # noqa: E402
from derive_metadata import derive_gender, derive_dept  # noqa: E402

# Paths
M7_ORG = ROOT / "m7_organized_v2"
DL = ROOT.parent / "stytrix-pipeline-Download0504"
M7_REPORT = DL / "data" / "ingest" / "metadata" / "m7_report.jsonl"
FACTS_ALIGNED = M7_ORG / "aligned" / "facts_aligned.jsonl"
VISION_FACTS = M7_ORG / "vision_facts.jsonl"
DESIGNS = M7_ORG / "designs.jsonl" if (M7_ORG / "designs.jsonl").exists() else DL / "data" / "ingest" / "metadata" / "designs.jsonl"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"
ISO_DICT = ROOT / "data" / "iso_dictionary.json"
CLIENT_CANON = ROOT / "data" / "client_canonical_mapping_v2.json"
OUT_DIR = ROOT / "outputs" / "platform"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_MASTER = OUT_DIR / "master.jsonl"

# Client name → 平台 brand code（10 brands cover 在 by_client）
CLIENT_TO_CODE = {
    "OLD NAVY": "ONY",
    "TARGET": "TGT",
    "GAP": "GAP",
    "GAP OUTLET": "GAP",  # merge 進 GAP
    "DICKS SPORTING GOODS": "DKS",
    "DICKS": "DKS",
    "ATHLETA": "ATH",
    "UNDER ARMOUR": "UA",
    "KOHLS": "KOH",
    "A & F": "ANF",
    "GU": "GU",
    "BEYOND YOGA": "BY",
}


def normalize_client(raw: str) -> str | None:
    if not raw:
        return None
    cleaned = raw.upper().split("(")[0].strip()
    return CLIENT_TO_CODE.get(cleaned)


def to_float(v):
    if v is None:
        return None
    s = str(v).replace(",", "")
    m = re.search(r"(-?\d+\.?\d*)", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def derive_item_type(design_id, program, item, subgroup, client, dept):
    """ITEM/SUBGROUP/CLIENT/DEPT → IT canonical（PANTS/LEGGINGS/JOGGERS/SHORTS/...）

    對齊 v6 邏輯，但簡化（v7 master 由 platform 主算 cascade）
    """
    text = f"{design_id} {program} {item} {subgroup}".upper()
    c = (client or "").upper()
    d = (dept or "").upper()
    if "LEGGING" in text or "TIGHT" in text: return "LEGGINGS"
    if "JOGGER" in text or "SWEATPANT" in text: return "JOGGERS"
    if "CAPRI" in text: return "CAPRI"
    if "SKIRT" in text or "SKORT" in text: return "SKIRT"
    if "SHORT" in text: return "SHORTS"
    if any(k in text for k in ["COMPRESSION", "POWERSOFT", "BUTTERSOFT", "STUDIOSMOOTH", "FLX"]):
        return "LEGGINGS"
    if c in {"BEYOND YOGA", "ATHLETA", "UNDER ARMOUR", "CALIA"} and d == "ACTIVE":
        return "LEGGINGS"
    return "PANT"


# ZH normalize（檔→襠 修簡體誤字）
ZH_NORMALIZE = {
    "檔底片": "襠底片",
    "褶底片": "襠底片",  # AI hallucinate fallback
}


def normalize_zh(s: str) -> str:
    if not s: return s
    for bad, good in ZH_NORMALIZE.items():
        s = s.replace(bad, good)
    return s


def strip_marker(s: str) -> str:
    if not s: return ""
    return normalize_zh(s.lstrip("*").strip())


def main():
    print("=" * 70)
    print("build_master_v7.py — Single Master Integration")
    print("=" * 70)

    # 1. Load M7 metadata index
    print("\n[1] Load M7 索引")
    df = load_m7_index()
    df["客戶_clean"] = df["客戶"].astype(str).str.split("(").str[0].str.strip().str.upper()
    g_map = {"Women": "WOMEN", "Men": "MEN", "Girl": "GIRL", "Boy": "BOY", "Baby": "BABY"}
    df["gender_excel"] = df["PRODUCT_CATEGORY"].astype(str).str.split().str[0].map(g_map).fillna("UNKNOWN")
    eidh_to_meta = {}
    for _, row in df.iterrows():
        eidh = row.get("Eidh")
        if not eidh: continue
        eidh = str(int(eidh))
        eidh_to_meta[eidh] = {
            "client": str(row["客戶_clean"]),
            "subgroup": str(row.get("Subgroup", "") or ""),
            "item": str(row.get("Item", "") or ""),
            "program": str(row.get("Program", "") or ""),
            "wk": str(row.get("W/K", "") or "").upper(),
            "season": str(row.get("Season", "") or ""),
            "design_id": str(row.get("報價款號", "") or ""),
            "gender_excel": row["gender_excel"],
        }
    print(f"    {len(eidh_to_meta)} EIDHs metadata loaded")

    # 2. Load zone_glossary L1 mapping
    print("\n[2] Load zone_glossary")
    g = json.load(open(ZONE_GLOSSARY, encoding="utf-8"))
    L1_zh_to_code = {zh: code for code, zh in g.get("L1_STANDARD_38", {}).items()}
    L1_code_to_zh = g.get("L1_STANDARD_38", {})
    print(f"    {len(L1_zh_to_code)} L1 mapping")

    # 3. Aggregate by (gender, dept, gt, it, fabric, l1) — 6-dim key + by_client breakdown
    print("\n[3] Walk m7_report 4644 EIDH → aggregate 6-dim + by_client")
    # outer: 6-dim key → inner aggregations
    agg = defaultdict(lambda: {
        "n_steps": 0,
        "iso_counter": Counter(),
        "method_counter": Counter(),
        "client_counter": Counter(),
        "design_ids": set(),
        "ie_total_seconds": 0.0,
        # by_client: client_code → {knit/woven → l2 → l3 → l4 → list of (l5, skill, sec, primary)}
        "by_client": defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))),
    })

    n_eidh_processed = 0
    n_step_processed = 0
    n_eidh_no_meta = 0

    if not M7_REPORT.exists():
        print(f"[!] {M7_REPORT} not found，無法 build master")
        return

    for line in open(M7_REPORT, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        eidh = str(r.get("eidh", ""))
        meta = eidh_to_meta.get(eidh)
        if not meta:
            n_eidh_no_meta += 1
            continue

        client_full = meta["client"]
        client_code = normalize_client(client_full)
        if not client_code:
            continue

        subgroup = meta["subgroup"]
        item = meta["item"]
        program = meta["program"]
        wk_raw = meta["wk"]
        fabric = "KNIT" if wk_raw.startswith("K") else ("WOVEN" if wk_raw.startswith("W") else "UNKNOWN")
        wk_lower = "knit" if fabric == "KNIT" else "woven"

        # gender / dept / it 推導
        gender = meta["gender_excel"] if meta["gender_excel"] != "UNKNOWN" else (derive_gender(client_full, subgroup) or "UNKNOWN")
        dept = derive_dept(client_full, program, subgroup) or "UNKNOWN"
        gt = "BOTTOM"  # all PullOn+Leggings 都是 BOTTOM
        it = derive_item_type(meta["design_id"], program, item, subgroup, client_full, dept)

        n_eidh_processed += 1
        design_id = meta["design_id"]

        for s in r.get("five_level_detail", []):
            cat = (s.get("category") or "").strip()
            l1_code = L1_zh_to_code.get(cat)
            if not l1_code:
                continue

            l2 = strip_marker(s.get("part") or "")
            l3 = strip_marker(s.get("shape_design") or "")
            l4 = strip_marker(s.get("method_describe_alt") or s.get("method_code") or "")
            l5 = normalize_zh((s.get("method_describe") or "").strip())
            skill = (s.get("skill_level") or s.get("Skill_Level") or "").strip()
            sec = to_float(s.get("total_second")) or 0.0
            primary = (s.get("primary") or s.get("主副") or "主").strip()
            iso = (s.get("iso") or s.get("ISO") or "").strip()
            method_en = (s.get("method_en") or s.get("Method") or "").strip().upper()

            if not l2 or not l3:
                continue

            # 6-dim key
            key = (gender, dept, gt, it, fabric, l1_code)
            entry = agg[key]
            entry["n_steps"] += 1
            entry["design_ids"].add(design_id)
            entry["client_counter"][client_code] += 1
            entry["ie_total_seconds"] += sec
            if iso: entry["iso_counter"][iso] += 1
            if method_en: entry["method_counter"][method_en] += 1
            n_step_processed += 1

            # by_client breakdown
            step_tuple = [l5 or l4, skill, sec, primary]
            entry["by_client"][client_code][wk_lower][l2][l3].setdefault(l4 or "?", []).append(step_tuple)

    print(f"    EIDH processed:   {n_eidh_processed}")
    print(f"    Steps processed:  {n_step_processed:,}")
    print(f"    EIDH no metadata: {n_eidh_no_meta}")
    print(f"    Unique 6-dim keys: {len(agg)}")

    # 4. Output master.jsonl
    print(f"\n[4] Output master.jsonl")
    n_written = 0
    with open(OUT_MASTER, "w", encoding="utf-8") as f:
        for (gender, dept, gt, it, fabric, l1), entry in sorted(agg.items()):
            n_total = entry["n_steps"]
            iso_dist = []
            for iso, n in entry["iso_counter"].most_common():
                pct = round(100 * n / n_total, 1)
                iso_dist.append({"iso": iso, "n": n, "pct": pct})
            methods = []
            for m, n in entry["method_counter"].most_common(10):
                pct = round(100 * n / n_total, 1)
                methods.append({"name": m, "n": n, "pct": pct})
            client_dist = []
            for c, n in entry["client_counter"].most_common():
                pct = round(100 * n / n_total, 1)
                client_dist.append({"client": c, "n": n, "pct": pct})

            # by_client → 結構化 list-of-l2-shapes
            by_client_out = {}
            for client_code, wk_dict in entry["by_client"].items():
                client_node = {"knit": [], "woven": []}
                for wk in ("knit", "woven"):
                    l2_dict = wk_dict.get(wk, {})
                    l2_list = []
                    for l2, l3_dict in l2_dict.items():
                        shapes = []
                        for l3, l4_dict in l3_dict.items():
                            l4_list = []
                            for l4, steps in l4_dict.items():
                                # dedup steps by (l5, skill)
                                seen = set()
                                unique_steps = []
                                for st in steps:
                                    sig = (st[0], st[1])
                                    if sig in seen: continue
                                    seen.add(sig)
                                    unique_steps.append(st)
                                l4_list.append({"l4": l4, "steps": unique_steps})
                            shapes.append({"l3": l3, "methods": l4_list})
                        l2_list.append({"l2": l2, "shapes": shapes})
                    client_node[wk] = l2_list
                client_node["n_designs"] = sum(1 for d in entry["design_ids"]
                                                if entry["client_counter"].get(client_code, 0) > 0)
                by_client_out[client_code] = client_node

            confidence = "high" if n_total >= 50 and len(entry["iso_counter"]) >= 1 else \
                         "medium" if n_total >= 10 else "low"

            master_entry = {
                "key": {
                    "gender": gender,
                    "dept": dept,
                    "gt": gt,
                    "it": it,
                    "fabric": fabric,
                    "l1": l1_code := l1
                },
                "source": "m7_pullon_v7",
                "aggregation_level": "same_bucket",
                "n_total": n_total,
                "confidence": confidence,
                "iso_distribution": iso_dist,
                "methods": methods,
                "client_distribution": client_dist,
                "by_client": by_client_out,
                "design_ids": sorted(list(entry["design_ids"]))[:50],  # 限 50 個避免太大
                "n_unique_designs": len(entry["design_ids"]),
                "ie_total_seconds": round(entry["ie_total_seconds"], 1),
                "_metadata": {
                    "build_version": "v7",
                    "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "source_file": "m7_report.jsonl",
                }
            }
            f.write(json.dumps(master_entry, ensure_ascii=False) + "\n")
            n_written += 1

    print(f"    Output: {OUT_MASTER}")
    print(f"    Entries: {n_written}")
    print(f"    File size: {OUT_MASTER.stat().st_size / 1024:.1f} KB")

    # 5. Stats
    print(f"\n=== Master Summary ===")
    print(f"  Source: m7_pullon_v7")
    print(f"  Total entries: {n_written}")
    by_it = Counter()
    by_fabric = Counter()
    by_dept = Counter()
    for line in open(OUT_MASTER, encoding="utf-8"):
        e = json.loads(line)
        by_it[e["key"]["it"]] += 1
        by_fabric[e["key"]["fabric"]] += 1
        by_dept[e["key"]["dept"]] += 1
    print(f"  By it:     {dict(by_it.most_common())}")
    print(f"  By fabric: {dict(by_fabric.most_common())}")
    print(f"  By dept:   {dict(by_dept.most_common())}")
    print(f"\n[next] push 到 platform repo:")
    print(f"  python scripts\\push_master_to_platform.py")


if __name__ == "__main__":
    main()
