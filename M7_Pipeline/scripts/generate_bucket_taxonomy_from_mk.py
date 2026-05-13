"""generate_bucket_taxonomy_from_mk.py — 從 MK Metadata 推導 bucket_taxonomy.json

⚠️ 重寫策略（v4.0）：
- 取代 platform 既有的手動編輯 bucket_taxonomy.json (59 buckets)
- 不再 hand-curate，從 MK Metadata cartesian product 自動產出

來源 (MK Metadata)：
  1. data/client_canonical_mapping.json (v3) - gender × dept × fabric × category 投票結果
  2. data/zone_glossary.json - L1 部位 enum (38)
  3. M7列管_*.xlsx - 實際 EIDH 組合（filter「實際出現過的」避免空 bucket）

產出 schema:
  buckets = {
    "WOMENS_ACTIVE_PANTS_LEGGINGS": {
      "gender": "WOMENS", "dept": "ACTIVE", "gt": "PANTS", "it": "LEGGINGS",
      "n_designs": 234,  // 從 M7 索引投票
      "fabric_split": {"KNIT": 230, "WOVEN": 4},
      "appears_in_sources": ["m7_pullon"],  // 哪些 source 提供
      "use_for": ["construction", "pom"]   // 做工 + POM 共用
    }
  }

POM 端 bucket 4 維（前 4 維 prefix），做工端 6 維（含 fabric + l1）。

跑：python scripts\\generate_bucket_taxonomy_from_mk.py
Output: data/bucket_taxonomy.json (v4，取代既有版)
"""
from __future__ import annotations
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from m7_eidh_loader import load_m7_index  # noqa: E402

CANON_PATH = ROOT / "data" / "client_canonical_mapping.json"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"
OUT = ROOT / "outputs" / "platform" / "bucket_taxonomy.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

# Item → it canonical (對齊 client_canonical_mapping_v2 的 enum)
ITEM_TO_IT = {
    "Pull On Pants": "PANT",
    "Pull On Dressy": "PANT_DRESSY",
    "Dressy Pants": "PANT_DRESSY",
    "Leggings": "LEGGINGS",
    "Shorts": "SHORTS",
    "Skirt": "SKIRT",
    "Skorts": "SKORT",
    "Tee": "BASIC_TOP",
    "Polo": "COLLARED_TOP",
    "Blouse/Shirts": "BLOUSE_SHIRT",
    "Camisole": "SLEEVELESS_TOP",
    "Jacket": "JACKET",
    "Vest": "VEST",
    "Coat": "COAT",
    "Blazer": "BLAZER",
    "Dress": "DRESS",
    "Gown": "GOWN",
    "Pajama": "PJ_SET",
    "Robe": "ROBE",
    "Boxer": "BOXER",
    "Panties": "PANTIES",
    "Swimwear": "SWIM",
    "Jumper": "JUMPER",
}

ITEM_TO_GT = {
    "Pull On Pants": "BOTTOM",
    "Pull On Dressy": "BOTTOM",
    "Dressy Pants": "BOTTOM",
    "Leggings": "BOTTOM",
    "Shorts": "SHORTS",
    "Skirt": "SKIRT",
    "Skorts": "SKIRT",
    "Tee": "TOP",
    "Polo": "TOP",
    "Blouse/Shirts": "TOP",
    "Camisole": "TOP",
    "Jacket": "OUTERWEAR",
    "Vest": "OUTERWEAR",
    "Coat": "OUTERWEAR",
    "Blazer": "OUTERWEAR",
    "Dress": "DRESS",
    "Gown": "DRESS",
    "Pajama": "SET",
    "Robe": "OUTERWEAR",
    "Boxer": "BOTTOM",
    "Panties": "UNDERWEAR",
    "Swimwear": "SWIMWEAR_PIECE",
    "Jumper": "ROMPER_JUMPSUIT",
}


def load_canon():
    if not CANON_PATH.exists():
        # 沒 v3 → fallback v2
        v2 = ROOT / "data" / "client_canonical_mapping_v2.json"
        if v2.exists():
            return json.load(open(v2, encoding="utf-8"))
        return None
    return json.load(open(CANON_PATH, encoding="utf-8"))


def main():
    print("=" * 70)
    print("generate_bucket_taxonomy_from_mk.py — 從 MK Metadata 推 bucket")
    print("=" * 70)

    # 1. Load MK Metadata
    canon = load_canon()
    if not canon:
        print(f"[!] {CANON_PATH} 不存在")
        sys.exit(1)
    print(f"[load] client_canonical_mapping: {len(canon.get('client_canonical_mapping', {}))} clients")

    df = load_m7_index()
    print(f"[load] M7 索引: {len(df)} rows")

    # 2. 從 M7 索引投票出 4 維 (gender × dept × gt × it) bucket
    print("\n[2] 從 M7 索引投票推導 4 維 bucket")

    df["客戶_clean"] = df["客戶"].astype(str).str.split("(").str[0].str.strip().str.upper()
    g_map = {"Women": "WOMEN", "Men": "MEN", "Girl": "GIRL", "Boy": "BOY", "Baby": "BABY"}
    df["gender"] = df["PRODUCT_CATEGORY"].astype(str).str.split().str[0].map(g_map).fillna("UNKNOWN")
    df["fabric"] = df["W/K"].astype(str).str.upper().str.replace("KNIT", "KNIT").str.replace("WOVEN", "WOVEN")
    df["fabric"] = df["fabric"].apply(lambda x: "KNIT" if x.startswith("K") else ("WOVEN" if x.startswith("W") else "UNKNOWN"))
    df["it"] = df["Item"].astype(str).map(ITEM_TO_IT).fillna("UNKNOWN")
    df["gt"] = df["Item"].astype(str).map(ITEM_TO_GT).fillna("UNKNOWN")

    # dept 從 client_canonical_mapping 推（subgroup 投票結果）
    canon_lookup = {}
    for client, info in canon.get("client_canonical_mapping", {}).items():
        for sg, meta in (info.get("subgroup_to_meta") or {}).items():
            dept_value = meta.get("dept", {}).get("value") if isinstance(meta.get("dept"), dict) else meta.get("dept")
            if dept_value and dept_value not in ("MIXED", "UNKNOWN"):
                canon_lookup[(client.upper(), sg.upper())] = dept_value

    def lookup_dept(row):
        c = row["客戶_clean"]
        sg = str(row.get("Subgroup", "") or "").upper()
        return canon_lookup.get((c, sg), "UNKNOWN")

    df["dept"] = df.apply(lookup_dept, axis=1)

    # Aggregate 4 維 bucket
    bucket_stats = defaultdict(lambda: {
        "n_designs": 0,
        "fabric_split": Counter(),
        "client_split": Counter(),
        "gender": "", "dept": "", "gt": "", "it": ""
    })

    for _, row in df.iterrows():
        gender = row["gender"]
        dept = row["dept"]
        gt = row["gt"]
        it = row["it"]
        fabric = row["fabric"]
        if gender == "UNKNOWN" or gt == "UNKNOWN" or it == "UNKNOWN" or dept == "UNKNOWN":
            continue
        bucket_key = f"{gender}_{dept}_{gt}_{it}"
        b = bucket_stats[bucket_key]
        b["gender"] = gender
        b["dept"] = dept
        b["gt"] = gt
        b["it"] = it
        b["n_designs"] += 1
        b["fabric_split"][fabric] += 1
        b["client_split"][row["客戶_clean"]] += 1

    print(f"    {len(bucket_stats)} unique 4-dim buckets (filter 實際出現)")

    # 3. Output bucket_taxonomy v4
    out = {
        "version": "v4",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Generated from MK Metadata (M7列管_5/7 18,731 EIDH + client_canonical_mapping)",
        "rule": (
            "從 MK Metadata cartesian product 過濾「實際出現過的 4 維組合」自動產出。"
            "key = <gender>_<dept>_<gt>_<it> (4 維)。"
            "做工 cascade 用 6 維 (4 維 + fabric + l1)，POM bucket 用 4 維 prefix。"
        ),
        "schema": {
            "key_format": "<GENDER>_<DEPT>_<GT>_<IT>",
            "dimensions": {
                "gender": ["WOMEN", "MEN", "GIRL", "BOY", "BABY", "MATERNITY", "UNISEX"],
                "dept": ["ACTIVE", "RTW", "SLEEPWEAR", "SWIMWEAR", "FLEECE", "DENIM"],
                "gt": ["BOTTOM", "TOP", "DRESS", "OUTERWEAR", "SET", "ROMPER_JUMPSUIT", "SKIRT", "SHORTS", "SWIMWEAR_PIECE", "UNDERWEAR"],
                "it": sorted(set(ITEM_TO_IT.values()))
            },
            "extra_dimensions": {
                "fabric": ["KNIT", "WOVEN"],
                "l1": "38 部位 (見 zone_glossary.json:L1_STANDARD_38)"
            }
        },
        "buckets": {}
    }

    # Sort by n_designs desc
    for bk, stat in sorted(bucket_stats.items(), key=lambda x: -x[1]["n_designs"]):
        out["buckets"][bk] = {
            "gender": stat["gender"],
            "dept": stat["dept"],
            "gt": stat["gt"],
            "it": stat["it"],
            "n_designs": stat["n_designs"],
            "fabric_split": dict(stat["fabric_split"].most_common()),
            "top_clients": dict(stat["client_split"].most_common(5)),
            "use_for": ["construction", "pom"]
        }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[output] {OUT}")
    print(f"  size: {OUT.stat().st_size:,} bytes")

    # Stats
    total_designs = sum(b["n_designs"] for b in out["buckets"].values())
    print(f"\n=== Stats ===")
    print(f"  Total 4-dim buckets:     {len(out['buckets'])}")
    print(f"  Total designs covered:   {total_designs}")
    print(f"  Top 10 buckets by size:")
    for i, (bk, info) in enumerate(list(out["buckets"].items())[:10]):
        print(f"    {bk:<40} {info['n_designs']:>4}")

    print(f"\n[next] 推到 platform：")
    print(f"  cp {OUT} ../stytrix-techpack/data/bucket_taxonomy.json")
    print(f"  # 取代既有 59 bucket 版本")


if __name__ == "__main__":
    main()
