"""backfill_gender_from_orderinfo.py — 從 order_info.jsonl 反推 (client, subgroup) → gender

讀 fetch_order_info.py 跑出來的 order_info.jsonl（含 product_category 真實值），
JOIN M7 索引拿 (client, subgroup)，反推 gender mapping，寫進
data/client_metadata_mapping.json + 印出 _MANUAL_MAPPING 補強清單。

跑完之後重跑 v3/v4/v5，UNKNOWN gender 應該降到接近 0。

用法：
  python scripts\\backfill_gender_from_orderinfo.py [--apply]

  --apply: 真的寫進 client_metadata_mapping.json
  不加 --apply 只 dry-run 印 plan
"""
from __future__ import annotations
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
ORDER_INFO = DL / "data" / "ingest" / "metadata" / "order_info.jsonl"
CLIENT_MAPPING = ROOT / "data" / "client_metadata_mapping.json"

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from m7_eidh_loader import load_m7_index

# Product Category → standard gender 對照
CATEGORY_TO_GENDER = {
    "Women 女士": "WOMEN",
    "Women": "WOMEN",
    "Men 男士": "MEN",
    "Men": "MEN",
    "Boy 男童": "BOY",
    "Boys": "BOY",
    "Boy": "BOY",
    "Girl 女童": "GIRL",
    "Girls": "GIRL",
    "Girl": "GIRL",
    "Kids 童裝": "KIDS",
    "Kids": "KIDS",
    "Baby": "BABY",
    "Newborn": "BABY",
    "Toddler": "KIDS",
}


def normalize_category(cat: str) -> str:
    """Product Category → standard gender code，找不到回 UNKNOWN"""
    if not cat:
        return "UNKNOWN"
    cat = cat.strip()
    # 先試完整 match
    if cat in CATEGORY_TO_GENDER:
        return CATEGORY_TO_GENDER[cat]
    # 試 partial match（前綴）
    for key, val in CATEGORY_TO_GENDER.items():
        if cat.startswith(key.split()[0]):
            return val
    return "UNKNOWN"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="真的寫進 mapping JSON")
    args = p.parse_args()

    if not ORDER_INFO.exists():
        print(f"[!] {ORDER_INFO} 不存在 — 先跑 fetch_order_info.py")
        return

    # 1. Load order_info.jsonl → style_no → product_category
    style_to_cat = {}
    total = real = 0
    for line in open(ORDER_INFO, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        total += 1
        sty = r.get("style_no")
        cat = r.get("product_category")
        if sty and cat:
            style_to_cat[sty] = cat
            real += 1
    print(f"[1] order_info.jsonl: {total} entries, {real} 有 product_category")

    if not real:
        print(f"[!] 沒任何 product_category — order_info 跑了嗎？")
        return

    # 2. Load M7 索引 → eidh × style × subgroup（用共用 helper，套 ITEM_FILTER）
    import pandas as pd
    try:
        df = load_m7_index()
    except FileNotFoundError as e:
        print(f"[!] {e}")
        return

    # 3. JOIN: 同 style 的所有 (client, subgroup) → product_category
    combo_to_cats = defaultdict(Counter)  # (client, subgroup) → Counter(category)
    matched = 0
    for _, row in df.iterrows():
        if not pd.notna(row.get("Eidh")):
            continue
        client = str(row.get("客戶", "") or "").strip().upper()
        sg = str(row.get("Subgroup", "") or "").strip()
        sty = str(row.get("報價款號", "") or "").strip()
        if not sty or sty not in style_to_cat:
            continue
        cat = style_to_cat[sty]
        gender = normalize_category(cat)
        if gender != "UNKNOWN":
            combo_to_cats[(client, sg)][gender] += 1
            matched += 1
    print(f"[2] M7 索引 JOIN: {matched} 筆有 gender")
    print(f"[3] {len(combo_to_cats)} 個 (client, subgroup) 組合有 ground truth gender")

    # 4. 對每個組合，挑出最高頻 gender 作 mapping
    mapping_to_apply = {}
    print(f"\n[4] (client, subgroup) → gender 推導:")
    for (client, sg), cnt in sorted(combo_to_cats.items(), key=lambda x: -sum(x[1].values())):
        total_n = sum(cnt.values())
        top_gender, top_n = cnt.most_common(1)[0]
        purity = top_n / total_n
        marker = "★" if purity >= 0.7 else " "
        if purity >= 0.7:
            mapping_to_apply[(client, sg)] = top_gender
        print(f"  {marker} {client[:25]:26} / {sg[:25]:26} → {top_gender:7} "
              f"({top_n}/{total_n}, purity={purity:.0%})")

    print(f"\n[5] {len(mapping_to_apply)} 組合可信度 ≥ 70%，會寫進 mapping")

    if not args.apply:
        print(f"\n  Dry-run only. 加 --apply 真寫")
        return

    # 5. 寫進 client_metadata_mapping.json
    if not CLIENT_MAPPING.exists():
        print(f"[!] {CLIENT_MAPPING} 不存在")
        return
    cfg = json.load(open(CLIENT_MAPPING, encoding="utf-8"))
    cfg.setdefault("clients", {})

    n_added = 0
    for (client, sg), gender in mapping_to_apply.items():
        client_key = client.replace(" ", "_").replace("&", "AND")
        client_data = cfg["clients"].setdefault(client_key, {})
        client_data.setdefault("client_name_aliases", [client])
        if client not in client_data["client_name_aliases"]:
            client_data["client_name_aliases"].append(client)
        sg_codes = client_data.setdefault("subgroup_codes", {})
        if sg in sg_codes:
            existing = sg_codes[sg].get("gender")
            if existing == gender:
                continue
            print(f"  [skip] {client}/{sg} 已有 {existing}，不覆蓋（new={gender}）")
        else:
            sg_codes[sg] = {"gender": gender, "name": f"{sg} (auto from order_info)"}
            n_added += 1

    with open(CLIENT_MAPPING, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"\n[6] 寫入 {CLIENT_MAPPING}, 新增 {n_added} 個 (client, subgroup)")
    print(f"\n[next] 重跑：")
    print(f"  python scripts\\build_platform_recipes_v3.py")
    print(f"  python scripts\\build_platform_recipes_v4.py")
    print(f"  python scripts\\build_recipes_master_v5.py")


if __name__ == "__main__":
    main()
