#!/usr/bin/env python3
"""Rebuild measurement_profiles_union.json from mc_pom_combined.jsonl"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pipeline_base import get_base_dir  # noqa: E402

# 2026-05-16: gender 改 data-driven, 走 data/source/gender_keywords.json
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from resolve_classification import resolve_gender as _resolve_gender_table


BASE = str(get_base_dir(description=__doc__))

def extract_gender(brand_division, department=''):
    bd = (brand_division or '').upper()
    dept = (department or '').upper()
    # Maternity is its own gender (different construction from WOMENS)
    if 'MATERNITY' in bd or 'MATERNITY' in dept:
        return 'MATERNITY'
    # BABY/TODDLER
    if 'BABY' in bd or 'TODDLER' in bd:
        return 'BABY/TODDLER'
    for g in ['GIRLS', 'BOYS', 'WOMENS', 'MENS']:
        if g in bd:
            return g
    # Fallback: check department for gender clues
    if 'TODDLER' in dept or 'BABY' in dept:
        return 'BABY/TODDLER'
    if 'BOYS' in dept:
        return 'BOYS'
    if 'GIRLS' in dept:
        return 'GIRLS'
    if 'WOMENS' in dept or 'WOMEN' in dept:
        return 'WOMENS'
    if 'MENS' in dept or ' MEN' in dept:
        return 'MENS'
    return 'UNKNOWN'


def resolve_gender(rec):
    """gender 解析 (2026-05-16 改 data-driven):
      T1 MATERNITY override (brand_division / department 含 MATERNITY) → MATERNITY
      T2 mk_gender — 聚陽 M7 列管 PRODUCT_CATEGORY 主路徑
      T3 (client, subgroup) canonical (從 client_canonical_mapping export)
      T4 subgroup tokens → gender_keywords.json
      T5 client default → gender_keywords.json
    所有 fallback 邏輯走 data/source/gender_keywords.json。
    """
    return _resolve_gender_table(rec)


profiles = []
# 2026-05-11: 自動讀三個分檔, 不再依賴 mc_pom_combined.jsonl
# (它不存在,且 PowerShell concat 會壞 UTF-8)
import glob
src_files = sorted(glob.glob(f'{BASE}/_parsed/mc_pom_*.jsonl'))
src_files = [s for s in src_files if 'combined' not in s.lower()]
if not src_files:
    print(f'[!] {BASE}/_parsed/ 內找不到 mc_pom_*.jsonl', file=sys.stderr)
    sys.exit(1)
print(f'[rebuild_profiles] reading {len(src_files)} files:')
for s in src_files: print(f'  {s}')

bad_lines = 0
all_lines_iter = []
for src in src_files:
    with open(src, 'r', encoding='utf-8') as f:
        all_lines_iter.extend(f.readlines())

for line in all_lines_iter:
        line = line.rstrip('\r\n')
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            bad_lines += 1
            continue
        mcs = rec.get('mcs', [])
        has_mc_pom = len(mcs) > 0

        # Build mc_poms list from mcs
        mc_poms = []
        all_sizes = set()
        body_types = set()
        for mc in mcs:
            bt = mc.get('body_type', '')
            if bt: body_types.add(bt)
            sizes_list = mc.get('sizes', [])
            all_sizes.update(sizes_list)
            for pom in mc.get('poms', []):
                mc_poms.append({
                    'code': pom.get('POM_Code', ''),
                    'name': pom.get('POM_Name', ''),
                    'sizes': pom.get('sizes', {}),
                    'tolerance': pom.get('tolerance', {}),
                    'body_type': bt
                })

        profiles.append({
            'design_id': rec.get('design_number', ''),
            # 2026-05-14: gender = M7列管 PRODUCT_CATEGORY 為主 + MATERNITY override.
            # 見 resolve_gender() docstring.
            'gender': resolve_gender(rec),
            'item_type': rec.get('item_type', ''),
            # 2026-05-14: 聚陽 canonical — manifest_item=Item(garment_type), mk_fabric=W/K(Knit/Woven).
            # reclassify_and_rebuild.py 的 real_gt_v2 / infer_fabric 優先吃這兩欄.
            'manifest_item': rec.get('manifest_item', ''),
            'mk_fabric': rec.get('mk_fabric', ''),
            'category': rec.get('category', ''),
            'department_raw': rec.get('department', ''),
            'brand_division': rec.get('brand_division', ''),
            # 2026-05-14: _client_code = 聚陽 canonical 3-letter brand code (adapter 從 M7列管 注入).
            # 帶到 reclassify / bodytype_variance, 讓 brand 維度走 canonical, 不硬解 brand_division.
            '_client_code': rec.get('_client_code', ''),
            'design_type': rec.get('design_type', ''),
            'description': rec.get('description', ''),
            'has_mc_pom': has_mc_pom,
            'mc_poms': mc_poms,
            'sizes': sorted(all_sizes),
            'body_types': sorted(body_types),
        })

output = {
    'source': 'mc_pom_{2024,2025,2026}.jsonl',
    'total': len(profiles),
    'with_mc_pom': sum(1 for p in profiles if p['has_mc_pom']),
    'profiles': profiles
}

out_path = f'{BASE}/measurement_profiles_union.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False)
print(f"\nBuilt {len(profiles):,} profiles ({output['with_mc_pom']:,} with mc_pom, {bad_lines} bad JSON skipped)")
# by brand_division 摘要
from collections import Counter
brand_count = Counter(p['brand_division'] for p in profiles if p['has_mc_pom'])
print(f"\nby brand_division (有 mc_pom, top 10):")
for b, n in brand_count.most_common(10):
    print(f"  {b or '(empty)':<40} {n:>6}")
print(f"\nSaved to {out_path}")
