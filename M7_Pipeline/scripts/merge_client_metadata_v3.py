"""merge_client_metadata_v3.py — 合併 v1 + v2 → v3 single client metadata bible

合併兩份檔成 v3：
  - v1: data/client_metadata_mapping.json      （22 客戶 subgroup_codes → gender + dept）
  - v2: data/client_canonical_mapping_v2.json  （38 客戶 subgroup_to_meta 4 維 ground truth）

Output: data/client_canonical_mapping.json (v3)
  - 含 v2 的 ground truth (4 維 with purity)
  - 含 v1 的 legacy subgroup_codes（提供 dept hard mapping，補 mixed gender 的 fallback）
  - 含 client_pdf_field_mappings placeholder（B 階段填）
  - 含 client_pdf_value_maps placeholder

跑：python scripts\\merge_client_metadata_v3.py
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V1_PATH = ROOT / "data" / "client_metadata_mapping.json"
V2_PATH = ROOT / "data" / "client_canonical_mapping_v2.json"
V3_PATH = ROOT / "data" / "client_canonical_mapping.json"

# Client name 對齊（v1 跟 v2 用不同主 key）
# v1 用 "ONY" 主 key，v2 用 "OLD NAVY" 主 key
# v3 統一用 v2 風格（M7 索引欄「客戶」原文）
V1_TO_V2_NAME = {
    "ONY": "OLD NAVY",
    "DICKS": "DICKS SPORTING GOODS",
    "TGT": "TARGET",
    "ATH": "ATHLETA",
    "UA": "UNDER ARMOUR",
    "KOH": "KOHLS",
    "BY": "BEYOND YOGA",
    "ANF": "A & F",
    "BR": "BANANA REPUBLIC",
    "HLF": "HIGH LIFE LLC",
}


def load_json(p: Path):
    if not p.exists():
        return None
    return json.load(open(p, encoding="utf-8"))


def main():
    print("=" * 70)
    print("merge_client_metadata_v3.py — 合併 v1 + v2 → v3")
    print("=" * 70)

    v1 = load_json(V1_PATH)
    v2 = load_json(V2_PATH)

    if not v1 and not v2:
        print("[!] 兩份 source 都不存在")
        sys.exit(1)

    if v1:
        print(f"[load] v1: {V1_PATH.name} ({len(v1.get('clients', {}))} clients)")
    else:
        print(f"[skip] v1 not found at {V1_PATH}")

    if v2:
        print(f"[load] v2: {V2_PATH.name} ({len(v2.get('client_canonical_mapping', {}))} clients)")
    else:
        print(f"[skip] v2 not found at {V2_PATH}")

    # 開始合並
    v3 = {
        "version": "v3",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filter_hierarchy": ["client", "fabric", "gender", "dept", "category"],
        "purity_threshold_pct": v2["purity_threshold_pct"] if v2 else 60,
        "rule": (
            "v3 合併版：v2 (4 維 ground truth from M7列管 5/7) + v1 (legacy subgroup_codes for fallback) + "
            "客戶 PDF metadata 欄位對照（B 階段補）。"
            "讀取優先序：subgroup_to_meta (v2) > legacy_subgroup_codes (v1) > _GENDER_TOKENS regex > _CLIENT_DEFAULT_*"
        ),
        "fallback_chain": [
            "1. M7 索引 PRODUCT_CATEGORY 直接對應（最強，每 EIDH 都有）",
            "2. (client, subgroup) 查 subgroup_to_meta (v2 ground truth)",
            "3. (client, subgroup) 查 legacy_subgroup_codes (v1 hard mapping)",
            "4. _GENDER_TOKENS regex (subgroup 含 MENS/MISSY/BOY/GIRL)",
            "5. _CLIENT_DEFAULT_GENDER / _CLIENT_DEFAULT_DEPT (client level default)",
            "6. UNKNOWN"
        ],
        "client_canonical_mapping": {}
    }

    # 從 v2 起步
    if v2:
        for client_name, info in v2.get("client_canonical_mapping", {}).items():
            v3["client_canonical_mapping"][client_name] = {
                "aliases": info.get("aliases", []),
                "n_total": info.get("n_total", 0),
                "subgroup_to_meta": info.get("subgroup_to_meta", {}),
                "subgroup_mixed_skipped": info.get("subgroup_mixed_skipped", []),
                # 從 v1 補 legacy 欄位（後面 patch 進來）
                "legacy_subgroup_codes": {},
                # B 階段填 client PDF metadata 對照
                "client_pdf_field_mappings": {},
                "client_pdf_value_maps": {},
            }

    # 把 v1 legacy 並進來
    if v1:
        v1_clients = v1.get("clients", {})
        for v1_key, v1_info in v1_clients.items():
            # 對齊 v3 client name（v1 ONY → v3 OLD NAVY）
            v3_key = V1_TO_V2_NAME.get(v1_key, v1_key)
            if v3_key in v3["client_canonical_mapping"]:
                # 已有 v2 entry，把 v1 legacy_subgroup_codes 加進來
                v3["client_canonical_mapping"][v3_key]["legacy_subgroup_codes"] = v1_info.get("subgroup_codes", {})
                # aliases 合並
                v1_aliases = set(v1_info.get("client_name_aliases", []))
                v1_aliases.add(v1_key)
                existing = set(v3["client_canonical_mapping"][v3_key].get("aliases", []))
                v3["client_canonical_mapping"][v3_key]["aliases"] = sorted(v1_aliases | existing)
            else:
                # v1 有但 v2 沒（小客戶），新建 entry
                v3["client_canonical_mapping"][v3_key] = {
                    "aliases": list(v1_info.get("client_name_aliases", [])) + [v1_key],
                    "n_total": 0,  # v1 沒記
                    "subgroup_to_meta": {},
                    "subgroup_mixed_skipped": [],
                    "legacy_subgroup_codes": v1_info.get("subgroup_codes", {}),
                    "client_pdf_field_mappings": {},
                    "client_pdf_value_maps": {},
                    "_legacy_only": True,
                }

    # Output
    V3_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(V3_PATH, "w", encoding="utf-8") as f:
        json.dump(v3, f, ensure_ascii=False, indent=2)
    size = V3_PATH.stat().st_size
    print(f"\n[output] {V3_PATH}")
    print(f"  size: {size:,} bytes")

    # Stats
    n_clients = len(v3["client_canonical_mapping"])
    n_with_meta = sum(1 for c in v3["client_canonical_mapping"].values() if c["subgroup_to_meta"])
    n_with_legacy = sum(1 for c in v3["client_canonical_mapping"].values() if c.get("legacy_subgroup_codes"))
    n_legacy_only = sum(1 for c in v3["client_canonical_mapping"].values() if c.get("_legacy_only"))
    print(f"\n=== v3 Stats ===")
    print(f"  Total clients:        {n_clients}")
    print(f"  with v2 4-dim meta:   {n_with_meta}")
    print(f"  with v1 legacy codes: {n_with_legacy}")
    print(f"  v1-only (no v2 data): {n_legacy_only}")
    print(f"\n  Pending B 階段（待填）:")
    print(f"    client_pdf_field_mappings: 空 placeholder")
    print(f"    client_pdf_value_maps:     空 placeholder")
    print(f"  → 用 inspect_client_pdf_fields.py 報告 review 後填")
    print(f"\n  舊檔處置建議：")
    print(f"    - {V1_PATH.name} 保留（derive_metadata.py 仍 fallback 讀）")
    print(f"    - {V2_PATH.name} 留做 backup（or 刪）")
    print(f"    - {V3_PATH.name} 是新 single source of truth")


if __name__ == "__main__":
    main()
