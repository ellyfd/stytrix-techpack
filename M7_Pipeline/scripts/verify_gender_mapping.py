"""verify_gender_mapping.py — 驗 client_canonical_mapping 對 18,731 EIDH 的 gender hit rate

跑：python scripts\verify_gender_mapping.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd
from derive_metadata import derive_gender, _CANONICAL_GENDER_MAPPING

ROOT = Path(__file__).resolve().parent.parent
M7_INDEX = ROOT.parent / "M7列管_20260507.xlsx"

print(f"Loaded canonical mapping: {len(_CANONICAL_GENDER_MAPPING)} entries")
print(f"Reading: {M7_INDEX.name} ...")
df = pd.read_excel(M7_INDEX, sheet_name="總表", engine="calamine")
n_total = len(df)
n_known = 0
n_canonical_hit = 0
n_unknown = 0

for _, row in df.iterrows():
    c = str(row["客戶"]).split("(")[0].strip().upper()
    sg = str(row.get("Subgroup", "") or "").upper().strip()
    g = derive_gender(c, sg)
    if g != "UNKNOWN":
        n_known += 1
    else:
        n_unknown += 1
    if (c, sg) in _CANONICAL_GENDER_MAPPING:
        n_canonical_hit += 1

print()
print(f"=== 結果 ===")
print(f"  Total rows:                  {n_total:>6}")
print(f"  Known gender:                {n_known:>6}  ({100*n_known/n_total:.1f}%)")
print(f"  UNKNOWN:                     {n_unknown:>6}  ({100*n_unknown/n_total:.1f}%)")
print(f"  Hit canonical mapping:       {n_canonical_hit:>6}  ({100*n_canonical_hit/n_total:.1f}%)")
print(f"  (剩餘 fallback):             {n_known - n_canonical_hit:>6}")
