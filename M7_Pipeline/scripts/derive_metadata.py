"""
derive_metadata.py — 從 M7 索引推 5 維 metadata (Brand / Fabric / Gender / Dept / Garment Type)

Gender 推導 4 段式：
  (1) PULL ON pure data 學出來的 (Customer, Subgroup) → Gender 對照表（auto，~79% 命中）
  (2) Subgroup 含 gender 字（MENS/MISSY/BOY/GIRL/KIDS 等）→ 直接命中（~6%）
  (3) Client-level rule：某些客戶全 WOMEN/MEN（BEYOND YOGA→WOMEN 等）
  (4) Manual mapping：user 提供的 client+subgroup 對照（~5%）

剩下標 UNKNOWN（業務需確認）。

用法：
  from derive_metadata import derive_metadata
  meta = derive_metadata(client, subgroup, item, program, wk, style)
"""

import re
import sys
from pathlib import Path
from collections import Counter

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PURE_PATH = ROOT / "PULL ON pure data.xlsx"

# 2026-05-16: 4 維度分類改 data-driven
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    from resolve_classification import (
        resolve_dept as _resolve_dept_table,
        resolve_gender as _resolve_gender_table,
        resolve_gt as _resolve_gt_table,
    )
except ImportError:
    # fallback: repo scripts/lib
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "lib"))
    from resolve_classification import (
        resolve_dept as _resolve_dept_table,
        resolve_gender as _resolve_gender_table,
        resolve_gt as _resolve_gt_table,
    )


# ════════════════════════════════════════════════════════════
# 段 1：PULL ON pure data 學出來的對照表
# ════════════════════════════════════════════════════════════

_AUTO_MAPPING = None

def _load_auto_mapping():
    """從 PULL ON pure data 載入 (Customer, Subgroup) → Gender 對照表"""
    global _AUTO_MAPPING
    if _AUTO_MAPPING is not None:
        return _AUTO_MAPPING
    if not PURE_PATH.exists():
        _AUTO_MAPPING = {}
        return _AUTO_MAPPING
    try:
        df = pd.read_excel(PURE_PATH, sheet_name="(MTM)五階層資料", engine="calamine")
    except (FileNotFoundError, OSError, ImportError) as e:
        # sandbox / engine 缺 → 靜默 fallback，靠段 2/3/4 補
        print(f"[derive_metadata] auto mapping skipped: {e}", file=sys.stderr)
        _AUTO_MAPPING = {}
        return _AUTO_MAPPING
    df["client_clean"] = df["Customer"].str.split("(").str[0].str.strip().str.upper()
    mapping = {}
    for (c, sg), grp in df.groupby(["client_clean", "SUBGROUP"]):
        if pd.isna(sg):
            continue
        gc = grp["Product Category"].value_counts()
        if len(gc) > 0:
            top = gc.index[0]
            purity = gc.iloc[0] / gc.sum()
            if purity >= 0.7:  # 至少 70% 純度才信
                mapping[(c, str(sg).upper())] = top.split()[0].upper()  # "Women 女士" → "WOMEN"
    _AUTO_MAPPING = mapping
    return mapping


# ════════════════════════════════════════════════════════════
# 段 2：Subgroup 含 gender 字
# ════════════════════════════════════════════════════════════

_GENDER_TOKENS = [
    # 男性
    (r"\bUA\(MENS\)|\bMENS\b|\bMEN'S\b|\bMEN\b|RTW\s*\(.*MEN.*\)|FLX\s*MEN|TG\s*MEN|A9\s*MEN", "MEN"),
    (r"\bMAC\b", "MEN"),  # Men Active Center (Kohls 等)
    # 女性
    (r"\bUA\(MISSY\)|\bMISSY\b|RTW\s*MISSY", "WOMEN"),
    (r"\bUA\(WMNS\)|\bWMNS\b|\bWOMEN\b|\bWOMENS\b|\bLADIES\b|FLX\s*WMN", "WOMEN"),
    (r"\bWAC\b", "WOMEN"),  # Women Active Center (Kohls)
    (r"\bSLW\b|SONOMA\s*WMN", "WOMEN"),  # Sonoma WoMeN (Kohls house brand)
    # 男童
    (r"\bUA\(BOYS\)|\bBOYS\b|\bBOY\b", "BOY"),
    (r"\bBAC\b", "BOY"),  # Boy Active Center
    # 女童
    (r"\bGIRLS\b|\bGIRL\b", "GIRL"),
    (r"\bGAC\b", "GIRL"),  # Girl Active Center
    # 不分性別童裝
    (r"\bKIDS\b|\bKID\b|\bTODDLER\b", "KIDS"),
    (r"\bBABY\b|\bINFANT\b|\bNEWBORN\b", "BABY"),
]


def _gender_from_subgroup(subgroup: str) -> str | None:
    if not subgroup:
        return None
    sg = subgroup.upper()
    for pat, g in _GENDER_TOKENS:
        if re.search(pat, sg):
            return g
    return None


# ════════════════════════════════════════════════════════════
# 段 3：Client-level rule（某些 client 預設全 gender）
# ════════════════════════════════════════════════════════════

_CLIENT_DEFAULT_GENDER = {
    "BEYOND YOGA": "WOMEN",
    "ATHLETA": "WOMEN",
    "CALIA": "WOMEN",
}

# Client-level default dept（當 subgroup/program 都缺時的 fallback）
# 用於修補 m7_report 直接抓的 EIDH 沒對應 design metadata 的情況
_CLIENT_DEFAULT_DEPT = {
    # ACTIVE（運動為主）
    "ATHLETA": "ACTIVE",
    "BEYOND YOGA": "ACTIVE",
    "DICKS SPORTING GOODS": "ACTIVE",
    "DICKS": "ACTIVE",
    "UNDER ARMOUR": "ACTIVE",
    "ASICS-EU": "ACTIVE",
    "ASICS": "ACTIVE",
    "DISTANCE": "ACTIVE",
    "KOHLS": "ACTIVE",  # Tek Gear 為主
    # RTW（普通服飾為主）
    "OLD NAVY": "RTW",
    "GAP": "RTW",
    "GAP OUTLET": "RTW",
    "A & F": "RTW",
    "ABERCROMBIE": "RTW",
    "TARGET": "RTW",
    "ZARA": "RTW",
    "QUINCE": "RTW",
    "GU": "RTW",
    "JOE FRESH": "RTW",
    "HIGH LIFE LLC": "RTW",
    "S1 DEVELOPING": "ACTIVE",  # XBODY 系列
    "WAL-MART": "RTW",
    "WAL-MART-CA": "RTW",
    "WMGP": "RTW",
}


# ════════════════════════════════════════════════════════════
# 段 4：User manual mapping
# ════════════════════════════════════════════════════════════

def _load_client_mapping():
    """從 data/client_metadata_mapping.json 載入每客戶的 subgroup_codes。
    格式：{(CLIENT, SUBGROUP): {"gender": ..., "dept": ...}}
    Source of truth — 改 mapping 改 JSON 即可，不要動 .py。
    """
    import json
    from pathlib import Path
    mapping_path = Path(__file__).resolve().parent.parent / "data" / "client_metadata_mapping.json"
    if not mapping_path.exists():
        return {}, {}
    with open(mapping_path, encoding="utf-8") as f:
        cfg = json.load(f)
    gender_map = {}
    dept_map = {}
    for client_key, info in cfg.get("clients", {}).items():
        # 用 client_name_aliases 全部展開，再 +大寫主 key
        aliases = list(info.get("client_name_aliases", []))
        aliases.append(client_key)
        # 都統一大寫
        aliases_upper = set(a.strip().upper() for a in aliases if a)
        for sg, attrs in (info.get("subgroup_codes") or {}).items():
            g = attrs.get("gender")
            d = attrs.get("dept")
            sg_up = sg.upper()
            for client_alias in aliases_upper:
                if g and g not in ("UNKNOWN", "MIXED"):
                    gender_map[(client_alias, sg_up)] = g
                if d and d not in ("UNKNOWN", "MIXED"):
                    dept_map[(client_alias, sg_up)] = d
    return gender_map, dept_map

_GENDER_MAPPING_FROM_JSON, _DEPT_MAPPING_FROM_JSON = _load_client_mapping()


# ════════════════════════════════════════════════════════════
# 段 2.5：MK Metadata canonical mapping（v3，2026-05-08 升級）
# 從 M7列管_20260507.xlsx 18,731 EIDH 投票推 4 維 ground truth：
#   (CLIENT, SUBGROUP) → {gender, dept, fabric, category}
# v3 schema: client_canonical_mapping[client]["subgroup_to_meta"][sg][dim]
#            + legacy_subgroup_codes (從 v1 並來，gender + dept fallback)
# ════════════════════════════════════════════════════════════

def _load_canonical_4dim_mapping():
    """從 data/client_canonical_mapping.json (v3) 載入 4 維 mapping。

    Returns:
        dict: {(CLIENT_ALIAS, SUBGROUP): {gender, dept, fabric, category}}
              其中每維為 high-purity (≥60%) value，否則為 None
              加上 legacy_subgroup_codes (v1 fallback)
    """
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "client_canonical_mapping.json"
    if not p.exists():
        return {}
    try:
        cfg = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for client_key, info in cfg.get("client_canonical_mapping", {}).items():
        aliases = set(a.strip().upper() for a in info.get("aliases", []))
        aliases.add(client_key.strip().upper())

        # v3: subgroup_to_meta (4 維 with purity)
        for sg, meta in (info.get("subgroup_to_meta") or {}).items():
            sg_up = sg.strip().upper()
            row = {}
            for dim in ["gender", "dept", "fabric", "category"]:
                v = meta.get(dim)
                if isinstance(v, dict):
                    val = v.get("value")
                    if val and val not in ("UNKNOWN", "MIXED"):
                        row[dim] = val
                elif v and v not in ("UNKNOWN", "MIXED"):
                    row[dim] = v
            if row:
                for alias in aliases:
                    out[(alias, sg_up)] = row

        # v1 legacy: subgroup_codes 補（gender + dept hard mapping）
        for sg, attrs in (info.get("legacy_subgroup_codes") or {}).items():
            sg_up = sg.strip().upper()
            for alias in aliases:
                key = (alias, sg_up)
                if key not in out:
                    out[key] = {}
                # v1 legacy 不蓋 v3 subgroup_to_meta（v3 優先）
                for dim in ["gender", "dept"]:
                    val = attrs.get(dim)
                    if val and val not in ("UNKNOWN", "MIXED") and dim not in out[key]:
                        out[key][dim] = val
    return out


_CANONICAL_4DIM_MAPPING = _load_canonical_4dim_mapping()

# 向後兼容：保留舊變數名（gender 一維 view），舊 code path 還能用
_CANONICAL_GENDER_MAPPING = {
    k: v["gender"] for k, v in _CANONICAL_4DIM_MAPPING.items() if "gender" in v
}


_MANUAL_MAPPING = {
    # 額外手動 case（不在 client_metadata_mapping.json 裡的舊客戶）
    ("WAL-MART-CA", "#D34"): "WOMEN",
    ("WAL-MART-CA", "#D23"): "MEN",
    ("WAL-MART-CA", "#D34K"): "WOMEN",
    ("WAL-MART", "D#23K"): "MEN",
    # 主要 mapping 已從 client_metadata_mapping.json 載入：
    #   ONY/TARGET/DICKS/GAP/GAP_OUTLET/BEYOND_YOGA 各 subgroup_codes
    # 若新增客戶 subgroup → gender 對照，改 JSON 即可
}
# Merge JSON-loaded mapping（JSON 優先，這裡是 fallback / 補強）
for k, v in _GENDER_MAPPING_FROM_JSON.items():
    _MANUAL_MAPPING.setdefault(k, v)


# ════════════════════════════════════════════════════════════
# 主推導
# ════════════════════════════════════════════════════════════

def derive_gender(client: str, subgroup: str) -> str:
    """改 data-driven (2026-05-16)。所有 fallback 走 data/source/gender_keywords.json
    + data/runtime/gender_lookup_by_subgroup.json。
    """
    return _resolve_gender_table({"client": client, "subgroup": subgroup})


def derive_dept(client: str, program: str, subgroup: str) -> str:
    """改 data-driven (2026-05-16)。Canonical enum v2 = 6 個 (ACTIVE/RTW/SWIMWEAR/SLEEPWEAR/DENIM/FLEECE)。
    COLLAB→ACTIVE; MATERNITY→GENDER。所有規則走 data/source/dept_keywords.json
    + data/runtime/dept_lookup_by_subgroup.json (從 client_canonical_mapping export)。
    """
    return _resolve_dept_table({"client": client, "program": program, "subgroup": subgroup})


def derive_garment_type(item: str) -> str:
    """改 data-driven (2026-05-16)。M7 manifest Item 原值優先, fallback 走 data/source/gt_keywords.json。"""
    return _resolve_gt_table({"mk_item": item, "item_type": item})


def derive_metadata(client: str, subgroup: str = "", item: str = "",
                    program: str = "", wk: str = "") -> dict:
    """5 維 metadata 推導，回傳 dict"""
    return {
        "brand": (client or "UNKNOWN").upper().strip(),
        "fabric": (wk or "UNKNOWN").upper().strip(),
        "gender": derive_gender(client, subgroup),
        "dept": derive_dept(client, program, subgroup),
        "garment_type": derive_garment_type(item),
    }


# ════════════════════════════════════════════════════════════
# CLI: 跑 1180 看推導率
# ════════════════════════════════════════════════════════════

def main():
    # 2026-05-08：用共用 helper（自動讀新版 5/7 + 套 ITEM_FILTER）
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from m7_eidh_loader import load_m7_index
    df = load_m7_index()

    rules_used = Counter()
    results = []
    for _, row in df.iterrows():
        if pd.isna(row.get("Eidh")):
            continue
        c = str(row["客戶"] or "")
        sg = str(row.get("Subgroup") or "")
        meta = derive_metadata(
            client=c,
            subgroup=sg,
            item=str(row.get("Item") or ""),
            program=str(row.get("Program") or ""),
            wk=str(row.get("W/K") or ""),
        )
        results.append(meta)

        # 標記是哪段命中
        c_up = c.upper().strip()
        sg_up = sg.upper().strip()
        auto = _load_auto_mapping()
        if (c_up, sg_up) in auto:
            rules_used["1_auto"] += 1
        elif _gender_from_subgroup(sg_up):
            rules_used["2_subgroup_token"] += 1
        elif c_up in _CLIENT_DEFAULT_GENDER:
            rules_used["3_client_default"] += 1
        elif (c_up, sg_up) in _MANUAL_MAPPING:
            rules_used["4_manual"] += 1
        else:
            rules_used["UNKNOWN"] += 1

    n_total = len(results)
    print(f"=== 1180 EIDH 5 維 metadata 推導 ===\n")

    print("[Gender 推導 by 段]:")
    for k in ["1_auto", "2_subgroup_token", "3_client_default", "4_manual", "UNKNOWN"]:
        n = rules_used.get(k, 0)
        print(f"  {k:20s} {n:>5} ({n/n_total*100:5.1f}%)")
    n_known = n_total - rules_used.get("UNKNOWN", 0)
    print(f"\n  Total 推到: {n_known}/{n_total} ({n_known/n_total*100:.1f}%)")

    print("\n[Gender 分布]:")
    for g, n in Counter(r["gender"] for r in results).most_common():
        print(f"  {g}: {n}")

    print("\n[Dept 分布]:")
    for d, n in Counter(r["dept"] for r in results).most_common():
        print(f"  {d}: {n}")

    print("\n[Brand × Fabric × Gender 5 維 unique 組合]:")
    combos = Counter()
    for r in results:
        combos[(r["brand"][:15], r["fabric"], r["gender"], r["dept"], r["garment_type"])] += 1
    print(f"  total: {len(combos)} unique")

if __name__ == "__main__":
    main()
