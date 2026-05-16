"""Build runtime cascade lookup tables from client_canonical_mapping.json (v2)

修法（2026-05-16）: schema 實際是 nested dict, 不是 flat list:
  client_canonical_mapping[CLIENT].subgroup_to_meta[SUBGROUP].dept.value

V2 changes from v1:
  - 修 schema parser, 走 nested traversal
  - 順便產 gender_lookup_by_subgroup.json (resolve_gender T3 用)
  - 加 purity_threshold (預設 60%, 跟 client_canonical_mapping.json:purity_threshold_pct 對齊)

CI Step 4e:
  python scripts/core/build_dept_lookup_by_subgroup.py
  → data/runtime/dept_lookup_by_subgroup.json
  → data/runtime/gender_lookup_by_subgroup.json

Format:
  { "<CLIENT_UPPER>|<SUBGROUP_UPPER>": "<DEPT_ENUM_v2 | GENDER_ENUM>" }

Canonical Dept enum v2 (6 個): ACTIVE / RTW / SWIMWEAR / SLEEPWEAR / DENIM / FLEECE
Canonical Gender enum: WOMENS / MENS / GIRLS / BOYS / BABY / MATERNITY

收斂規則:
  - COLLABORATION / NFL / NBA → ACTIVE
  - MATERNITY → 不入 Dept (拔到 GENDER), 跳過
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CANONICAL_MAPPING = ROOT / "data" / "client_canonical_mapping.json"
OUT_DIR = ROOT / "data" / "runtime"


def normalize_dept_v1_to_v2(v: str | None) -> str | None:
    """v1 dept enum (各種大小寫) → v2 canonical 6 enum。MATERNITY → None (拔到 GENDER)."""
    if not v or not isinstance(v, str):
        return None
    u = v.upper().strip()
    if u in ("MATERNITY", "MTR"):
        return None  # 拔出 Dept
    if u in ("COLLABORATION", "COLLAB", "NFL", "NBA", "MISCSPORTS"):
        return "ACTIVE"  # v2 併 ACTIVE
    if u in ("ACTIVE",):
        return "ACTIVE"
    if u in ("SLEEPWEAR", "SLEEP"):
        return "SLEEPWEAR"
    if u in ("SWIMWEAR", "SWIM"):
        return "SWIMWEAR"
    if u in ("FLEECE",):
        return "FLEECE"
    if u in ("DENIM",):
        return "DENIM"
    if u in ("RTW",):
        return "RTW"
    return None  # UNKNOWN 或 罕見值, 不輸出


def normalize_gender(v: str | None) -> str | None:
    """gender enum canonical normalize. M7 列管寫 WOMEN/MEN/GIRL/BOY/BABY (單數),前端用複數。"""
    if not v or not isinstance(v, str):
        return None
    u = v.upper().strip()
    if u in ("WOMEN", "WOMENS"):
        return "WOMENS"
    if u in ("MEN", "MENS"):
        return "MENS"
    if u in ("GIRL", "GIRLS"):
        return "GIRLS"
    if u in ("BOY", "BOYS"):
        return "BOYS"
    if u in ("BABY", "TODDLER", "INFANT"):
        return "BABY"
    if u in ("MATERNITY",):
        return "MATERNITY"
    return None


def build_lookups(canonical_data: dict, purity_threshold: int = 60):
    """Walk nested schema, produce {client|subgroup: dept} and {client|subgroup: gender}.

    Schema:
      client_canonical_mapping: {
        "<CLIENT>": {
          "subgroup_to_meta": {
            "<SUBGROUP>": {
              "dept": {"value": "ACTIVE", "purity": 100},
              "gender": {"value": "WOMEN", "purity": 98},
              ...
            }
          }
        }
      }
    """
    top = canonical_data.get("client_canonical_mapping", {})

    dept_lookup = {}
    gender_lookup = {}
    skipped = {"dept_low_purity": 0, "dept_normalize_fail": 0,
               "gender_low_purity": 0, "gender_normalize_fail": 0,
               "dept_maternity_skip": 0}

    for client, client_data in top.items():
        if not isinstance(client_data, dict):
            continue
        subgroups = client_data.get("subgroup_to_meta", {})
        if not isinstance(subgroups, dict):
            continue
        for subgroup, sg_meta in subgroups.items():
            if not isinstance(sg_meta, dict):
                continue
            key = f"{client.upper().strip()}|{subgroup.upper().strip()}"

            # dept
            dept_obj = sg_meta.get("dept", {})
            if isinstance(dept_obj, dict):
                dept_val = dept_obj.get("value")
                dept_purity = dept_obj.get("purity", 0)
                if dept_purity >= purity_threshold:
                    dept_v2 = normalize_dept_v1_to_v2(dept_val)
                    if dept_v2:
                        dept_lookup[key] = dept_v2
                    elif dept_val and dept_val.upper().strip() in ("MATERNITY", "MTR"):
                        skipped["dept_maternity_skip"] += 1
                    else:
                        skipped["dept_normalize_fail"] += 1
                else:
                    skipped["dept_low_purity"] += 1

            # gender
            gender_obj = sg_meta.get("gender", {})
            if isinstance(gender_obj, dict):
                gender_val = gender_obj.get("value")
                gender_purity = gender_obj.get("purity", 0)
                if gender_purity >= purity_threshold:
                    gender_canon = normalize_gender(gender_val)
                    if gender_canon:
                        gender_lookup[key] = gender_canon
                    else:
                        skipped["gender_normalize_fail"] += 1
                else:
                    skipped["gender_low_purity"] += 1

    return dept_lookup, gender_lookup, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--purity", type=int, default=60, help="purity threshold pct (default 60)")
    args = ap.parse_args()

    if not CANONICAL_MAPPING.exists():
        print(f"[ERROR] {CANONICAL_MAPPING} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(CANONICAL_MAPPING.read_text(encoding="utf-8"))
    dept_lookup, gender_lookup, skipped = build_lookups(data, purity_threshold=args.purity)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Dept lookup
    dept_path = OUT_DIR / "dept_lookup_by_subgroup.json"
    dept_path.write_text(json.dumps({
        "_description": "Department T1 cascade lookup — 從 client_canonical_mapping.json:subgroup_to_meta export",
        "_generator": "scripts/core/build_dept_lookup_by_subgroup.py",
        "_source": "data/client_canonical_mapping.json (v3, 4 維 ground truth)",
        "_canonical_enum_v2": ["ACTIVE", "RTW", "SWIMWEAR", "SLEEPWEAR", "DENIM", "FLEECE"],
        "_purity_threshold_pct": args.purity,
        "_n_entries": len(dept_lookup),
        "_skipped_low_purity": skipped["dept_low_purity"],
        "_skipped_normalize_fail": skipped["dept_normalize_fail"],
        "_skipped_maternity": skipped["dept_maternity_skip"],
        "_consumer": "scripts/lib/resolve_classification.py:resolve_dept() T1",
        "lookup": dept_lookup,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {dept_path}: {len(dept_lookup)} entries (skipped: low_purity={skipped['dept_low_purity']}, normalize_fail={skipped['dept_normalize_fail']}, maternity={skipped['dept_maternity_skip']})")

    # Gender lookup
    gender_path = OUT_DIR / "gender_lookup_by_subgroup.json"
    gender_path.write_text(json.dumps({
        "_description": "Gender T3 cascade lookup — 從 client_canonical_mapping.json:subgroup_to_meta export",
        "_generator": "scripts/core/build_dept_lookup_by_subgroup.py",
        "_source": "data/client_canonical_mapping.json (v3, 4 維 ground truth)",
        "_canonical_enum": ["WOMENS", "MENS", "GIRLS", "BOYS", "BABY", "MATERNITY"],
        "_purity_threshold_pct": args.purity,
        "_n_entries": len(gender_lookup),
        "_skipped_low_purity": skipped["gender_low_purity"],
        "_skipped_normalize_fail": skipped["gender_normalize_fail"],
        "_consumer": "scripts/lib/resolve_classification.py:resolve_gender() T3",
        "lookup": gender_lookup,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {gender_path}: {len(gender_lookup)} entries (skipped: low_purity={skipped['gender_low_purity']}, normalize_fail={skipped['gender_normalize_fail']})")


if __name__ == "__main__":
    main()
