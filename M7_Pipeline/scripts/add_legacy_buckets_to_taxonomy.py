"""add_legacy_buckets_to_taxonomy.py — 在 v4 bucket_taxonomy 加 legacy_buckets section

Background：v4 master schema 目前 scope = M7 PullOn (BOTTOM × PANT/LEGGINGS, 28 buckets)。
但 platform 端 facts/consensus 還有 1910/275 筆 用舊 3-dim bucket name (TOPS/OUTER/DRESS/SET/...)。
直接切會掉 2185 筆 entry。

Solution：在 v4 加 `legacy_buckets` section，每筆舊 bucket name → 對應 3-dim expansion。
build_recipes_master 的 load_bucket_taxonomy() 兩 section 都讀，cascade 不變動。

未來 v4 master schema 涵蓋更廣 product type 後，legacy_buckets 才漸退。

跑：python scripts/add_legacy_buckets_to_taxonomy.py
輸出：直接更新 platform 的 data/bucket_taxonomy.json（in-place, 加 legacy_buckets section）
"""
from __future__ import annotations
import json
from pathlib import Path

import os
# 跑在 Windows: PLATFORM = C:\temp\stytrix-techpack
# 跑在 Linux sandbox: PLATFORM = /sessions/.../mnt/stytrix-techpack
_DEFAULT_PLATFORM = (
    "/sessions/exciting-sweet-curie/mnt/stytrix-techpack"
    if os.path.exists("/sessions/exciting-sweet-curie/mnt/stytrix-techpack")
    else "C:/temp/stytrix-techpack"
)
PLATFORM = Path(os.environ.get("PLATFORM_REPO", _DEFAULT_PLATFORM))
TAX_PATH = PLATFORM / "data" / "bucket_taxonomy.json"

# === Old 3-dim bucket name → expansion (gender / dept / gt 列表) ===
# 舊 schema 規則：
#   {GENDER}_{KEY2}_{KEY3}
#   GENDER: BOYS/GIRLS/MENS/WOMENS/MATERNITY/NEWBORN/TODDLER/OTHER
#   KEY2:   PERF=ACTIVE/KNIT=fabric only/WOVEN=fabric only/FLEECE=dept/RTW/SWIM/SLEEP/DRESS
#   KEY3:   BOTTOMS/TOPS/OUTER/DRESS/SET/SLEEP/SWIM/MISC

# Gender 正規化（複數 → 單數對齊 v4 schema）
GENDER_MAP = {
    "BOYS": ["BOY"],
    "GIRLS": ["GIRL"],
    "MENS": ["MEN"],
    "WOMENS": ["WOMEN"],
    "MATERNITY": ["MATERNITY"],
    "NEWBORN": ["BABY"],
    "TODDLER": ["BABY"],
    "OTHER": ["UNISEX", "WOMEN", "MEN", "GIRL", "BOY", "BABY"],  # OTHER → fan-out
}

# Dept 推導（KEY2 segment 對應 v4 dept value）
DEPT_FROM_KEY2 = {
    "PERF": ["ACTIVE"],          # performance = active
    "FLEECE": ["FLEECE"],
    "KNIT": ["RTW", "ACTIVE", "SLEEPWEAR"],   # KNIT 是 fabric，跨 dept；fan-out
    "WOVEN": ["RTW", "ACTIVE"],               # WOVEN 是 fabric，跨 dept
    "RTW": ["RTW"],
    "SWIM": ["SWIMWEAR"],
    "SLEEP": ["SLEEPWEAR"],
    "DRESS": ["RTW"],            # GIRLS_DRESS / WOMENS_DRESS → RTW dept
    # 沒 KEY2 ( e.g. MATERNITY_BOTTOMS ): 預設 RTW
    "_DEFAULT": ["RTW"],
}

# GT 推導（KEY3 segment）
GT_FROM_KEY3 = {
    "BOTTOMS": ["BOTTOM"],
    "TOPS": ["TOP"],
    "OUTER": ["OUTERWEAR"],
    "DRESS": ["DRESS"],
    "SET": ["SET"],
    "SLEEP": ["SET"],            # *_SLEEP 視為 SET (PJ_SET) 的簡稱
    "SWIM": ["SWIMWEAR_PIECE"],
    "MISC": ["TOP", "BOTTOM"],   # MISC fan-out
    "BOTTOMS_TOPS": ["BOTTOM", "TOP"],   # 雙 GT bucket
    # 特殊 fingerprint case
    "_DEFAULT": ["TOP"],
}

# Special-case 完整 bucket name 對照（規則推導不出來時）
SPECIAL_MAP = {
    "BOYS_SLEEP": {"gender": ["BOY"], "dept": ["SLEEPWEAR"], "gt": ["SET"]},
    "GIRLS_SET": {"gender": ["GIRL"], "dept": ["RTW"], "gt": ["SET"]},
    "GIRLS_SLEEP": {"gender": ["GIRL"], "dept": ["SLEEPWEAR"], "gt": ["SET"]},
    "GIRLS_SLEEP_SLEEP": {"gender": ["GIRL"], "dept": ["SLEEPWEAR"], "gt": ["SET"]},
    "GIRLS_DRESS": {"gender": ["GIRL"], "dept": ["RTW"], "gt": ["DRESS"]},
    "GIRLS_DRESS_BOTTOMS": {"gender": ["GIRL"], "dept": ["RTW"], "gt": ["BOTTOM", "DRESS"]},
    "GIRLS_DRESS_TOPS": {"gender": ["GIRL"], "dept": ["RTW"], "gt": ["TOP", "DRESS"]},
    "WOMENS_DRESS": {"gender": ["WOMEN"], "dept": ["RTW"], "gt": ["DRESS"]},
    "WOMENS_DRESS_BOTTOMS": {"gender": ["WOMEN"], "dept": ["RTW"], "gt": ["BOTTOM", "DRESS"]},
    "WOMENS_SLEEP": {"gender": ["WOMEN"], "dept": ["SLEEPWEAR"], "gt": ["SET"]},
    "MENS_KNIT_SLEEP": {"gender": ["MEN"], "dept": ["SLEEPWEAR"], "gt": ["SET"]},
    "WOMENS_WOVEN_SLEEP": {"gender": ["WOMEN"], "dept": ["SLEEPWEAR"], "gt": ["SET"]},
    "MATERNITY_BOTTOMS": {"gender": ["MATERNITY"], "dept": ["RTW"], "gt": ["BOTTOM"]},
    "MATERNITY_DRESS": {"gender": ["MATERNITY"], "dept": ["RTW"], "gt": ["DRESS"]},
    "MATERNITY_OUTER": {"gender": ["MATERNITY"], "dept": ["RTW"], "gt": ["OUTERWEAR"]},
    "MATERNITY_SET": {"gender": ["MATERNITY"], "dept": ["RTW"], "gt": ["SET"]},
    "MATERNITY_TOPS": {"gender": ["MATERNITY"], "dept": ["RTW"], "gt": ["TOP"]},
    "NEWBORN_DRESS": {"gender": ["BABY"], "dept": ["RTW"], "gt": ["DRESS"]},
    "NEWBORN_MISC": {"gender": ["BABY"], "dept": ["RTW"], "gt": ["TOP", "BOTTOM"]},
    "NEWBORN_SET": {"gender": ["BABY"], "dept": ["RTW"], "gt": ["SET"]},
    "NEWBORN_SWIM": {"gender": ["BABY"], "dept": ["SWIMWEAR"], "gt": ["SWIMWEAR_PIECE"]},
    "TODDLER_SLEEP": {"gender": ["BABY"], "dept": ["SLEEPWEAR"], "gt": ["SET"]},
    "OTHER_SWIM": {"gender": ["UNISEX", "WOMEN", "MEN", "GIRL", "BOY"], "dept": ["SWIMWEAR"], "gt": ["SWIMWEAR_PIECE"]},
}


def expand_legacy_bucket(name: str) -> dict | None:
    """老 bucket name → {gender:[...], dept:[...], gt:[...]} expansion。

    Returns None 表示無法解析。
    """
    name = name.upper()
    if name in SPECIAL_MAP:
        return SPECIAL_MAP[name].copy()

    parts = name.split("_")
    if len(parts) < 2:
        return None

    gender_raw = parts[0]
    gender = GENDER_MAP.get(gender_raw)
    if not gender:
        return None

    # 嘗試解 KEY2 + KEY3
    if len(parts) == 3:
        key2, key3 = parts[1], parts[2]
        dept = DEPT_FROM_KEY2.get(key2, DEPT_FROM_KEY2["_DEFAULT"])
        gt = GT_FROM_KEY3.get(key3, GT_FROM_KEY3["_DEFAULT"])
    elif len(parts) == 2:
        # 沒中段，KEY2 段直接是 KEY3
        key23 = parts[1]
        dept = DEPT_FROM_KEY2["_DEFAULT"]
        gt = GT_FROM_KEY3.get(key23, GT_FROM_KEY3["_DEFAULT"])
    else:
        # 4+ parts，多半 SPECIAL_MAP cover 過了；fallback 取前 3 段
        return None

    return {"gender": gender, "dept": dept, "gt": gt}


def main():
    tax = json.load(open(TAX_PATH, encoding="utf-8"))

    # 既存 v4 bucket names
    v4_bucket_names = set(tax.get("buckets", {}).keys())

    # 從 platform facts/consensus 收集 unique 舊 bucket name
    legacy_names = set()
    for path in [
        PLATFORM / "data" / "ingest" / "consensus_v1" / "entries.jsonl",
        PLATFORM / "data" / "ingest" / "consensus_rules" / "facts.jsonl",
        PLATFORM / "data" / "ingest" / "construction_by_bucket" / "facts.jsonl",
        PLATFORM / "data" / "ingest" / "ocr_v1" / "facts.jsonl",
    ]:
        if not path.exists():
            continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            b = row.get("key", {}).get("bucket") if "key" in row else row.get("bucket", "")
            if b:
                b = b.upper()
                if b not in v4_bucket_names:
                    legacy_names.add(b)

    print(f"[legacy] 偵測到 {len(legacy_names)} 個舊 bucket names 不在 v4")

    # Build legacy_buckets section
    legacy_buckets = {}
    unresolved = []
    for name in sorted(legacy_names):
        exp = expand_legacy_bucket(name)
        if exp is None:
            unresolved.append(name)
            continue
        legacy_buckets[name] = {
            **exp,
            "_legacy_3dim": True,
            "note": "舊 3-dim bucket name；對應 v4 4-dim 由 fan-out 推導（沒精確 IT）"
        }

    if unresolved:
        print(f"[!] 解不出: {unresolved}")

    # 寫入
    tax["legacy_buckets"] = legacy_buckets
    tax["legacy_note"] = (
        "舊 3-dim bucket name (gender/key2/key3) → 3-dim expansion list。"
        "build_recipes_master 的 load_bucket_taxonomy() 把 buckets (4-dim) + legacy_buckets (3-dim) 合併用。"
        "等 v4 master schema 涵蓋更廣 product type 後，legacy_buckets 漸退。"
    )

    # backup
    bak = TAX_PATH.with_suffix(".json.bak")
    if not bak.exists():
        TAX_PATH.replace(bak)
        # restore + rewrite
        json.dump(tax, open(TAX_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"[backup] {bak}")
    else:
        json.dump(tax, open(TAX_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"[output] {TAX_PATH}")
    print(f"  v4 buckets:      {len(v4_bucket_names)}")
    print(f"  legacy_buckets:  {len(legacy_buckets)}")
    print(f"  unresolved:      {len(unresolved)}")
    if unresolved:
        for u in unresolved:
            print(f"    - {u}")


if __name__ == "__main__":
    main()
