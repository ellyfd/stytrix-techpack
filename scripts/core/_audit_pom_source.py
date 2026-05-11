"""Quick audit: check source_brand_distribution 真實內容 in pom_rules buckets."""
import json
import os
from pathlib import Path

POM = Path(r"C:\temp\stytrix-techpack\pom_rules")
BASE = Path(os.environ.get(
    "POM_PIPELINE_BASE",
    r"C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\ONY",
))

print("=" * 70)
print("  bucket source_brand_distribution 抽 3 個樣本")
print("=" * 70)
files = [
    POM / "womens_active_top.json",
    POM / "womens_rtw_top.json",
    POM / "womens_active_dress.json",
]
for fp in files:
    if not fp.exists():
        print(f"  {fp.name}: NOT FOUND")
        continue
    with open(fp, encoding="utf-8") as f:
        d = json.load(f)
    bucket = d.get("bucket")
    n = d.get("n")
    primary = d.get("source_brand")
    dist = d.get("source_brand_distribution")
    print(f"\n  {fp.name}")
    print(f"    bucket  = {bucket}")
    print(f"    n       = {n}")
    print(f"    primary = {primary!r}")
    print(f"    dist    = {dist}")

print()
print("=" * 70)
print("  全 125 bucket source_brand_distribution 統計")
print("=" * 70)
multi = single = empty = 0
total_brands = set()
for fp in POM.glob("*.json"):
    if fp.name in ("_index.json", "pom_names.json"):
        continue
    with open(fp, encoding="utf-8") as f:
        d = json.load(f)
    dist = d.get("source_brand_distribution") or {}
    total_brands.update(dist.keys())
    if not dist:
        empty += 1
    elif len(dist) == 1:
        single += 1
    else:
        multi += 1
print(f"  multi-brand bucket: {multi}")
print(f"  single-brand bucket: {single}")
print(f"  empty dist bucket:   {empty}")
print(f"  全部 brand 出現過: {sorted(total_brands)}")

print()
print("=" * 70)
print("  measurement_profiles_union.json 內 brand_division 樣本")
print("=" * 70)
union_path = BASE / "measurement_profiles_union.json"
with open(union_path, encoding="utf-8") as f:
    pdata = json.load(f)
total_has_mc = sum(1 for p in pdata["profiles"] if p.get("has_mc_pom"))
print(f"  total profiles: {len(pdata['profiles'])}")
print(f"  has_mc_pom:     {total_has_mc}")
print(f"\n  前 5 個 has_mc_pom 樣本:")
shown = 0
for p in pdata["profiles"]:
    if p.get("has_mc_pom") and shown < 5:
        print(f"    design={p.get('design_id')!r}, brand_division={p.get('brand_division')!r}")
        shown += 1
