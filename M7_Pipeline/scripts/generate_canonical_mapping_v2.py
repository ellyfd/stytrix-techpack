"""generate_canonical_mapping_v2.py — 用 ground truth 投票推 5 維 canonical mapping

聚陽 IE filter hierarchy：
  client → fabric (W/K) → gender (PRODUCT_CATEGORY) → dept → category (= item type)

對每 (客戶, Subgroup) 從 18,731 EIDH 投票推 5 維。

跑：python scripts\\generate_canonical_mapping_v2.py
輸出：data/client_canonical_mapping_v2.json
"""
from __future__ import annotations
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from m7_eidh_loader import load_m7_index  # noqa: E402

OUT = ROOT / "data" / "client_canonical_mapping_v2.json"

# === 5 維 enum ===
GENDER_MAP = {
    "Women": "WOMEN", "Men": "MEN", "Girl": "GIRL", "Boy": "BOY", "Baby": "BABY"
}

# Item → category (canonical it 細品類)
ITEM_TO_CATEGORY = {
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
    "Chemise": "CHEMISE",
    "Pajama": "PJ_SET",
    "Pajama 3PC": "PJ_3PC",
    "Pajama Top": "PJ_TOP",
    "Pajama Bottom": "PJ_BOTTOM",
    "Robe": "ROBE",
    "Boxer": "BOXER",
    "Panties": "PANTIES",
    "Swimwear": "SWIM",
    "Jumper": "JUMPER",
    "Suit": "SUIT",
    "Coverall": "COVERALL",
    "Accessories": "ACCESSORY",
    "Blanket": "BLANKET",
    "Graphic Tee": "GRAPHIC_TOP",
}

# Subgroup keyword → dept（聚陽自家 active center 編碼 + 客戶系列）
SUBGROUP_TO_DEPT_KEYWORDS = {
    "ACTIVE": [
        "ACT", "WAC", "MAC", "BAC", "GAC", "FLX", "VRST", "TG ", "TEK GEAR",
        "PERFORMANCE", "COMPRESSION", "POWERSOFT", "BUTTERSOFT", "STUDIOSMOOTH",
        "BOUNCE", "MOMENTUM", "JOURNEY", "DSG", "CALIA", "UA(", "ATHLETA",
        "BEYOND YOGA", "AIM", "CHAMPION", "GOLF", "PRO ", "SPORT"
    ],
    "SLEEPWEAR": [
        "SLW", "SLEEPWEAR", "PJ", "PAJAMA", "LOUNGE", "SONOMA", "SO JUNIOR",
        "CB ", "INTIMATE"
    ],
    "RTW": [
        "RTW", "FASHION", "SEASONAL", "TSD", "WKN", "KNIT TOP",
        "BRFS", "DRESSY", "MISSY", "NET", "QUINCE", "WOVEN"
    ],
    "SWIMWEAR": ["SWIM", "RASHGUARD", "SU "],
    "FLEECE": ["FLEECE", "FR ", "F.R."],
    "MATERNITY": ["MTR", "MATERNITY", "MAT "],
    "DENIM": ["DENIM", "JEANS"],
}


def infer_dept_from_subgroup(subgroup: str, program: str = "", item: str = "") -> str:
    """從 subgroup + program + item 推 dept"""
    text = f"{subgroup} {program} {item}".upper()
    # 特殊：Item 是 Pajama / Robe / Camisole / Gown / Chemise → SLEEPWEAR
    if any(it in (item or "") for it in ["Pajama", "Robe", "Gown", "Chemise"]):
        return "SLEEPWEAR"
    if item == "Swimwear":
        return "SWIMWEAR"
    if item in ("Boxer", "Panties"):
        return "INTIMATE"
    # 從 subgroup keyword 推
    for dept, keywords in SUBGROUP_TO_DEPT_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return dept
    return "RTW"  # default


def main():
    df = load_m7_index()
    df["客戶_clean"] = df["客戶"].astype(str).str.split("(").str[0].str.strip().str.upper()
    df["gender_value"] = df["PRODUCT_CATEGORY"].astype(str).str.split().str[0].map(GENDER_MAP).fillna("UNKNOWN")
    df["fabric_value"] = df["W/K"].astype(str).str.upper()
    df["dept_value"] = df.apply(
        lambda r: infer_dept_from_subgroup(
            str(r.get("Subgroup", "") or ""),
            str(r.get("Program", "") or ""),
            str(r.get("Item", "") or "")
        ), axis=1
    )
    df["category_value"] = df["Item"].astype(str).map(ITEM_TO_CATEGORY).fillna("UNKNOWN")

    PURITY_THRESHOLD = 60

    out = {
        "version": "v2",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": f"M7列管_20260507.xlsx 總表 18,731 EIDH × 5-dim ground truth",
        "purity_threshold_pct": PURITY_THRESHOLD,
        "filter_hierarchy": ["client", "fabric", "gender", "dept", "category"],
        "rule": (
            f"每維 purity >= {PURITY_THRESHOLD}% 才進 mapping。"
            "<60% 標記 MIXED，由下游 fallback chain 處理。"
        ),
        "enums": {
            "gender": ["WOMEN", "MEN", "GIRL", "BOY", "BABY", "UNKNOWN"],
            "fabric": ["KNIT", "WOVEN"],
            "dept": ["ACTIVE", "RTW", "SLEEPWEAR", "SWIMWEAR", "FLEECE", "MATERNITY", "DENIM", "INTIMATE"],
            "category": sorted(set(ITEM_TO_CATEGORY.values()))
        },
        "client_canonical_mapping": {}
    }

    def vote_dim(grp, col):
        votes = Counter(grp[col].dropna().astype(str))
        if not votes:
            return None
        top, top_n = votes.most_common(1)[0]
        n = len(grp)
        purity = round(top_n / n * 100)
        result = {
            "value": top if purity >= PURITY_THRESHOLD else "MIXED",
            "purity": purity,
            "n": n,
            "votes": dict(votes.most_common(5))
        }
        return result

    client_totals = df.groupby("客戶_clean").size().to_dict()

    # 客戶別名表（補進 mapping，給 derive_metadata.py 用 alias 對應）
    CLIENT_ALIASES = {
        "OLD NAVY": ["ONY", "ON", "OLD NAVY", "OLDNAVY"],
        "DICKS SPORTING GOODS": ["DICKS", "DSG", "DICKS SPORTING GOO", "DICKS SPORTING GOODS"],
        "TARGET": ["TARGET", "TGT"],
        "ATHLETA": ["ATHLETA", "ATH"],
        "UNDER ARMOUR": ["UNDER ARMOUR", "UA", "UNDERARMOUR"],
        "KOHLS": ["KOHLS", "KOHL'S", "KOH"],
        "BEYOND YOGA": ["BEYOND YOGA", "BY"],
        "GU": ["GU"],
        "A & F": ["A & F", "ANF", "ABERCROMBIE"],
        "BANANA REPUBLIC": ["BANANA REPUBLIC", "BR"],
        "HIGH LIFE LLC": ["HIGH LIFE LLC", "HLF"],
        "GAP": ["GAP"],
        "GAP OUTLET": ["GAP OUTLET", "GAPO"],
        "WAL-MART": ["WAL-MART", "WALMART"],
        "WAL-MART-CA": ["WAL-MART-CA", "WALMART-CA"],
        "QUINCE": ["QUINCE"],
        "ZARA": ["ZARA"],
        "JOE FRESH": ["JOE FRESH"],
        "ASICS-EU": ["ASICS-EU", "ASICS"],
        "HALARA": ["HALARA"],
        "CALIA": ["CALIA"],
        "DISTANCE": ["DISTANCE"],
        "LEVIS": ["LEVIS", "LEVI'S"],
        "OAKLEY": ["OAKLEY"],
        "CATO": ["CATO"],
        "SANMAR": ["SANMAR"],
        "NET": ["NET"],
        "GILDAN": ["GILDAN"],
    }

    for client_name, cgrp in df.groupby("客戶_clean"):
        if len(cgrp) < 5: continue  # skip tiny clients
        sg_map = {}
        for sg, sgrp in cgrp.groupby("Subgroup"):
            if not sg or str(sg).strip() == "": continue
            sg_map[str(sg)] = {
                "n_total": len(sgrp),
                "fabric": vote_dim(sgrp, "fabric_value"),
                "gender": vote_dim(sgrp, "gender_value"),
                "dept": vote_dim(sgrp, "dept_value"),
                "category": vote_dim(sgrp, "category_value")
            }
        # alias 列（給 derive_metadata 用 alias 找 client）
        aliases = CLIENT_ALIASES.get(client_name, [client_name])
        # 確保主 key 在 aliases 內
        if client_name not in aliases:
            aliases.append(client_name)
        out["client_canonical_mapping"][client_name] = {
            "aliases": sorted(set(a.strip().upper() for a in aliases)),
            "n_total": len(cgrp),
            "subgroup_to_meta": sg_map
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    size = OUT.stat().st_size
    print(f"[output] {OUT}")
    print(f"  size: {size:,} bytes")

    # Stats
    n_clients = len(out["client_canonical_mapping"])
    n_subgroups = sum(len(c["subgroup_to_meta"]) for c in out["client_canonical_mapping"].values())
    n_pure = {dim: 0 for dim in ["fabric", "gender", "dept", "category"]}
    for c in out["client_canonical_mapping"].values():
        for sg_meta in c["subgroup_to_meta"].values():
            for dim in n_pure:
                if sg_meta.get(dim) and sg_meta[dim]["value"] != "MIXED":
                    n_pure[dim] += 1
    print(f"\n=== 統計 ===")
    print(f"  Clients:    {n_clients}")
    print(f"  Subgroups:  {n_subgroups}")
    print(f"  各維 high-purity (≥{PURITY_THRESHOLD}%) 比例:")
    for dim in ["fabric", "gender", "dept", "category"]:
        pct = round(100 * n_pure[dim] / n_subgroups) if n_subgroups else 0
        print(f"    {dim:<10} {n_pure[dim]:>4}/{n_subgroups}  ({pct}%)")


if __name__ == "__main__":
    main()
