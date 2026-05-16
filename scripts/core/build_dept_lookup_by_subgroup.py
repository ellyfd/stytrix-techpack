"""Build data/runtime/dept_lookup_by_subgroup.json from data/client_canonical_mapping.json

Run as CI Step 4e (跟 Step 4d build_brand_alias 同位階):
  python3 scripts/core/build_dept_lookup_by_subgroup.py

Output: data/runtime/dept_lookup_by_subgroup.json
  Format: { "<CLIENT_UPPER>|<SUBGROUP_UPPER>": "<DEPT_ENUM_v2>" }

Canonical Dept enum v2 (6 個):
  ACTIVE / RTW / SWIMWEAR / SLEEPWEAR / DENIM / FLEECE

Source key: client_canonical_mapping.json[*]["dept"] 或 ["department"] 欄
  - 原值若是 v1 enum (Active/Sleepwear/Swimwear/Fleece/Collaboration/RTW/MATERNITY 各種大小寫) 統一收斂到 v2
  - COLLABORATION → ACTIVE
  - MATERNITY → 不入 Dept (拔到 GENDER override), 跳過
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CANONICAL_MAPPING = ROOT / "data" / "client_canonical_mapping.json"
OUTPUT = ROOT / "data" / "runtime" / "dept_lookup_by_subgroup.json"


def normalize_dept_v1_to_v2(v1_value: str) -> str | None:
    """v1 enum → v2 enum 收斂。MATERNITY 回 None (跳過, 不入 Dept)."""
    if not v1_value or not isinstance(v1_value, str):
        return None
    v = v1_value.upper().strip()
    if v in ("MATERNITY", "MTR"):
        return None  # 拔出 Dept, 放 GENDER
    if v in ("COLLABORATION", "COLLAB", "NFL", "NBA"):
        return "ACTIVE"  # v2 併 ACTIVE
    if v in ("ACTIVE",):
        return "ACTIVE"
    if v in ("SLEEPWEAR", "SLEEP"):
        return "SLEEPWEAR"
    if v in ("SWIMWEAR", "SWIM"):
        return "SWIMWEAR"
    if v in ("FLEECE",):
        return "FLEECE"
    if v in ("DENIM",):
        return "DENIM"
    if v in ("RTW",):
        return "RTW"
    return None  # UNKNOWN / 其他 → 不輸出


def main():
    if not CANONICAL_MAPPING.exists():
        print(f"[ERROR] {CANONICAL_MAPPING} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(CANONICAL_MAPPING.read_text(encoding="utf-8"))

    # data 是 list of dict, 每筆有 client / subgroup / dept 等欄位
    # 實際 schema 視 client_canonical_mapping_v3 而定, 兼容多種 key 命名
    lookup = {}
    skipped_maternity = 0
    skipped_unknown = 0

    if isinstance(data, dict):
        # 可能是 { "client_canonical_mapping": [...] } 包裝
        entries = data.get("client_canonical_mapping") or data.get("entries") or data.get("data") or []
    elif isinstance(data, list):
        entries = data
    else:
        entries = []

    for ent in entries:
        if not isinstance(ent, dict):
            continue
        client = ent.get("client") or ent.get("client_canonical") or ent.get("Client") or ""
        subgroup = ent.get("subgroup") or ent.get("Subgroup") or ent.get("subgroup_code") or ""
        dept_raw = ent.get("dept") or ent.get("department") or ent.get("Department") or ""

        if not client or not subgroup:
            continue

        dept_v2 = normalize_dept_v1_to_v2(dept_raw)
        if dept_v2 is None:
            if dept_raw and dept_raw.upper().strip() in ("MATERNITY", "MTR"):
                skipped_maternity += 1
            else:
                skipped_unknown += 1
            continue

        key = f"{client.upper().strip()}|{subgroup.upper().strip()}"
        lookup[key] = dept_v2

    # 包頭 metadata
    output = {
        "_description": "Department T1 cascade lookup table — 從 client_canonical_mapping.json export, 用 CI Step 4e 重生",
        "_generator": "scripts/core/build_dept_lookup_by_subgroup.py",
        "_source": "data/client_canonical_mapping.json",
        "_canonical_enum_v2": ["ACTIVE", "RTW", "SWIMWEAR", "SLEEPWEAR", "DENIM", "FLEECE"],
        "_n_entries": len(lookup),
        "_skipped_maternity": skipped_maternity,
        "_skipped_unknown": skipped_unknown,
        "lookup": lookup,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] {OUTPUT} written: {len(lookup)} entries")
    print(f"     skipped: maternity={skipped_maternity}  unknown={skipped_unknown}")


if __name__ == "__main__":
    main()
