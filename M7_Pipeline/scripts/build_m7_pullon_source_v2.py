"""build_m7_pullon_source_v2.py — DEPRECATED 2026-05-08

⛔ 此 script 已被 build_m7_pullon_source_v3.py 取代,僅留作 reference。

v3 vs v2 差別:
- v2 只輸出 m7_pullon_source.jsonl (aggregated by 6-dim key)
- v3 兩 output:
    1. m7_pullon_source.jsonl  — 同 v2
    2. m7_pullon_designs.jsonl — per-EIDH 完整履歷 (M7 列管 42 cols + m7_report 33 cols + 完整 csv rows)
- v3 fabric 改成 multi-source consensus (m7_wk + bom + machine + subgroup + item)

請改用: python scripts\\build_m7_pullon_source_v3.py

== 以下為 v2 原註解,僅供 reference ==

build_m7_pullon_source_v2.py — Step 2 source publisher (csv_5level edition)
從 csv_5level/*.csv (raw SSRS rows per EIDH) 抽 — 完整 L1-L5 + machine + skill + grade
"""

import sys
print("[!] DEPRECATED: build_m7_pullon_source_v2.py replaced by v3.", file=sys.stderr)
print("    Use: python scripts\\build_m7_pullon_source_v3.py", file=sys.stderr)
sys.exit(2)

# ── below: v2 original code, kept for reference but unreachable ──
_DEPRECATED_GUARD = True

"""(v2 original code below kept for reference)
"""
from __future__ import annotations
import csv
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
CSV_5LEVEL_DIR = M7_ORG / "csv_5level"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"
OUT_DIR = ROOT / "outputs" / "platform"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_SOURCE = OUT_DIR / "m7_pullon_source.jsonl"

# Filename pattern: <EIDH>_<other_id>_<CLIENT_NAME>_<style_no>[_<ver>].csv
# Example: 304080_10405493_OLD_NAVY_ONY25HOVDD01_2.csv
FILENAME_RE = re.compile(r"^(\d+)_")

# Client name → 平台 brand code (10 brands)
CLIENT_TO_CODE = {
    "OLD NAVY": "ONY",
    "TARGET": "TGT",
    "GAP": "GAP",
    "GAP OUTLET": "GAP",
    "DICKS SPORTING GOODS": "DKS",
    "DICKS": "DKS",
    "ATHLETA": "ATH",
    "UNDER ARMOUR": "UA",
    "KOHLS": "KOH",
    "A & F": "ANF",
    "GU": "GU",
    "BEYOND YOGA": "BY",
}

# ZH normalize (檔→襠 修簡體誤字)
ZH_NORMALIZE = {
    "檔底片": "襠底片",
    "褶底片": "襠底片",
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


def normalize_zh(s: str) -> str:
    if not s:
        return s
    for bad, good in ZH_NORMALIZE.items():
        s = s.replace(bad, good)
    return s


def strip_marker(s: str) -> str:
    if not s:
        return ""
    return normalize_zh(s.lstrip("*").strip())


def derive_item_type(design_id, program, item, subgroup, client, dept):
    """ITEM/SUBGROUP/CLIENT/DEPT → IT canonical (PANT/LEGGINGS/JOGGERS/SHORTS/CAPRI/SKIRT)"""
    text = f"{design_id} {program} {item} {subgroup}".upper()
    c = (client or "").upper()
    d = (dept or "").upper()
    if "LEGGING" in text or "TIGHT" in text:
        return "LEGGINGS"
    if "JOGGER" in text or "SWEATPANT" in text:
        return "JOGGERS"
    if "CAPRI" in text:
        return "CAPRI"
    if "SKIRT" in text or "SKORT" in text:
        return "SKIRT"
    if "SHORT" in text:
        return "SHORTS"
    if any(k in text for k in ["COMPRESSION", "POWERSOFT", "BUTTERSOFT", "STUDIOSMOOTH", "FLX"]):
        return "LEGGINGS"
    if c in {"BEYOND YOGA", "ATHLETA", "UNDER ARMOUR", "CALIA"} and d == "ACTIVE":
        return "LEGGINGS"
    return "PANT"


def parse_csv_row(row: dict, l1_zh_to_code: dict) -> dict | None:
    """每 csv row → step dict (None 表示跳過)"""
    cat = (row.get("category") or "").strip()
    l1_code = l1_zh_to_code.get(cat)
    if not l1_code:
        return None

    l2 = strip_marker(row.get("part") or "")
    l3 = strip_marker(row.get("Shape_Design") or "")
    l4 = strip_marker(row.get("Method_Describe") or "")
    l5 = normalize_zh((row.get("section") or "").strip())
    if not (l2 and l3 and l4 and l5):
        return None

    skill = (row.get("Skill_Level") or "").strip()
    primary = (row.get("Sewing_Process") or "主").strip()
    machine = (row.get("machine_name") or "").strip()
    size = (row.get("size") or "").strip()
    sec = to_float(row.get("total_second")) or 0.0

    return {
        "l1": l1_code, "l2": l2, "l3": l3, "l4": l4, "l5": l5,
        "skill": skill, "primary": primary, "machine": machine,
        "size": size, "sec": sec,
    }


def main():
    print("=" * 70)
    print("build_m7_pullon_source_v2.py — Step 2 Source (csv_5level)")
    print("=" * 70)
    print(f"Source dir: {CSV_5LEVEL_DIR}")
    print(f"Output:     {OUT_SOURCE}")
    print()

    # 1. Load M7 index → EIDH metadata
    print("[1] Load M7 索引")
    df = load_m7_index()
    df["客戶_clean"] = df["客戶"].astype(str).str.split("(").str[0].str.strip().str.upper()
    g_map = {"Women": "WOMEN", "Men": "MEN", "Girl": "GIRL", "Boy": "BOY", "Baby": "BABY"}
    df["gender_excel"] = df["PRODUCT_CATEGORY"].astype(str).str.split().str[0].map(g_map).fillna("UNKNOWN")
    eidh_to_meta = {}
    for _, row in df.iterrows():
        eidh = row.get("Eidh")
        if not eidh:
            continue
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
    print(f"    {len(eidh_to_meta):,} EIDHs metadata loaded")

    # 2. Load zone_glossary L1 mapping
    print("\n[2] Load zone_glossary (Bible L1)")
    g = json.load(open(ZONE_GLOSSARY, encoding="utf-8"))
    L1_zh_to_code = {zh: code for code, zh in g.get("L1_STANDARD_38", {}).items()}
    print(f"    {len(L1_zh_to_code)} L1 mapping")

    # 3. Walk csv_5level/*.csv → aggregate by 5+1 維 key
    print(f"\n[3] Walk csv_5level → aggregate")
    if not CSV_5LEVEL_DIR.exists():
        print(f"[!] csv_5level dir not found: {CSV_5LEVEL_DIR}")
        return

    csv_files = sorted(CSV_5LEVEL_DIR.glob("*.csv"))
    print(f"    {len(csv_files):,} csv files found")

    agg = defaultdict(lambda: {
        "n_steps": 0,
        "iso_counter": Counter(),       # csv 沒 ISO 欄,留空
        "method_counter": Counter(),    # csv 沒 method_en,留空
        "client_counter": Counter(),
        "design_ids": set(),
        "ie_total_seconds": 0.0,
        # by_client[client][knit/woven][l2][l3][l4]: list of l5 step dicts
        "by_client": defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))),
    })

    n_files_ok = 0
    n_files_no_meta = 0
    n_rows_total = 0
    n_rows_processed = 0

    for csv_path in csv_files:
        m = FILENAME_RE.match(csv_path.name)
        if not m:
            continue
        eidh = m.group(1)
        meta = eidh_to_meta.get(eidh)
        if not meta:
            n_files_no_meta += 1
            continue

        client_full = meta["client"]
        client_code = normalize_client(client_full)
        if not client_code:
            continue

        wk_raw = meta["wk"]
        fabric = "KNIT" if wk_raw.startswith("K") else ("WOVEN" if wk_raw.startswith("W") else "UNKNOWN")
        wk_lower = "knit" if fabric == "KNIT" else "woven"

        gender = meta["gender_excel"] if meta["gender_excel"] != "UNKNOWN" else (derive_gender(client_full, meta["subgroup"]) or "UNKNOWN")
        dept = derive_dept(client_full, meta["program"], meta["subgroup"]) or "UNKNOWN"
        gt = "BOTTOM"
        it = derive_item_type(meta["design_id"], meta["program"], meta["item"], meta["subgroup"], client_full, dept)
        design_id = meta["design_id"]

        try:
            with open(csv_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                file_processed = False
                for row in reader:
                    n_rows_total += 1
                    parsed = parse_csv_row(row, L1_zh_to_code)
                    if not parsed:
                        continue
                    n_rows_processed += 1
                    file_processed = True

                    # 5+1 維 key
                    key = (gender, dept, gt, it, fabric, parsed["l1"])
                    entry = agg[key]
                    entry["n_steps"] += 1
                    entry["design_ids"].add(design_id)
                    entry["client_counter"][client_code] += 1
                    entry["ie_total_seconds"] += parsed["sec"]

                    # by_client → knit/woven → L2 → L3 → L4 → list of L5 step dicts
                    l5_step = {
                        "l5": parsed["l5"],
                        "skill": parsed["skill"],
                        "primary": parsed["primary"],
                        "machine": parsed["machine"],
                        "size": parsed["size"],
                        "sec": parsed["sec"],
                    }
                    entry["by_client"][client_code][wk_lower][parsed["l2"]][parsed["l3"]][parsed["l4"]].append(l5_step)
                if file_processed:
                    n_files_ok += 1
        except Exception as e:
            print(f"    [skip] {csv_path.name}: {e}", file=sys.stderr)

    print(f"    Files OK:         {n_files_ok:,} / {len(csv_files):,}")
    print(f"    Files no meta:    {n_files_no_meta:,}")
    print(f"    Rows total:       {n_rows_total:,}")
    print(f"    Rows processed:   {n_rows_processed:,}")
    print(f"    Unique 6-dim keys: {len(agg):,}")

    # 4. Output entries.jsonl
    print(f"\n[4] Output {OUT_SOURCE.name}")
    n_written = 0
    with open(OUT_SOURCE, "w", encoding="utf-8") as f:
        for (gender, dept, gt, it, fabric, l1), entry in sorted(agg.items()):
            n_total = entry["n_steps"]
            client_dist = []
            for c, n in entry["client_counter"].most_common():
                pct = round(100 * n / n_total, 1)
                client_dist.append({"client": c, "n": n, "pct": pct})

            # by_client structured output (proper 5-tier hierarchy)
            by_client_out = {}
            for client_code, wk_dict in entry["by_client"].items():
                client_node = {"knit": [], "woven": []}
                for wk in ("knit", "woven"):
                    l2_dict = wk_dict.get(wk, {})
                    l2_list = []
                    for l2, l3_dict in l2_dict.items():
                        shapes = []
                        for l3, l4_dict in l3_dict.items():
                            methods = []
                            for l4, l5_steps in l4_dict.items():
                                # Dedup L5 by (name, skill, primary)
                                seen = set()
                                unique_steps = []
                                for st in l5_steps:
                                    sig = (st["l5"], st["skill"], st["primary"])
                                    if sig in seen:
                                        continue
                                    seen.add(sig)
                                    unique_steps.append(st)
                                methods.append({"l4": l4, "l5_steps": unique_steps})
                            shapes.append({"l3": l3, "methods": methods})
                        l2_list.append({"l2": l2, "shapes": shapes})
                    client_node[wk] = l2_list
                client_node["n_designs"] = sum(
                    1 for d in entry["design_ids"]
                    if entry["client_counter"].get(client_code, 0) > 0
                )
                by_client_out[client_code] = client_node

            confidence = "high" if n_total >= 50 else "medium" if n_total >= 10 else "low"

            source_entry = {
                "key": {
                    "gender": gender, "dept": dept, "gt": gt,
                    "it": it, "fabric": fabric, "l1": l1,
                },
                "source": "m7_pullon",
                "aggregation_level": "same_bucket",
                "n_total": n_total,
                "confidence": confidence,
                "iso_distribution": [],          # csv_5level 沒 ISO,要 callout 補
                "methods": [],                   # csv_5level 沒 method_en,要 callout 補
                "client_distribution": client_dist,
                "by_client": by_client_out,
                "design_ids": sorted(list(entry["design_ids"]))[:50],
                "n_unique_designs": len(entry["design_ids"]),
                "ie_total_seconds": round(entry["ie_total_seconds"], 1),
                "_metadata": {
                    "build_version": "v2_csv_5level",
                    "step": "step2_source",
                    "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "raw_source_dir": str(CSV_5LEVEL_DIR.relative_to(ROOT)),
                    "schema_note": "by_client.<client>.<knit|woven>[].l2 → shapes[].l3 → methods[].l4 → l5_steps[]"
                                   " (proper 5-tier; vs v1 which mislabeled L5 as l4)",
                },
            }
            f.write(json.dumps(source_entry, ensure_ascii=False) + "\n")
            n_written += 1

    print(f"    Output: {OUT_SOURCE}")
    print(f"    Entries: {n_written:,}")
    if OUT_SOURCE.exists():
        print(f"    File size: {OUT_SOURCE.stat().st_size / 1024:.1f} KB")
    print(f"\n[next] push 到 platform repo:")
    print(f"  cp {OUT_SOURCE} ../stytrix-techpack/data/ingest/m7_pullon/entries.jsonl")
    print(f"  cd ../stytrix-techpack && git add data/ingest/m7_pullon/entries.jsonl")
    print(f"  git commit -m 'feat(data): m7_pullon source v2 (csv_5level)'")
    print(f"  git push  # 觸發 GitHub Actions rebuild_master.yml")


if __name__ == "__main__":
    main()
