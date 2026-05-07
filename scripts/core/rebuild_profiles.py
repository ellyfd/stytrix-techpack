#!/usr/bin/env python3
"""Rebuild measurement_profiles_union.json from mc_pom_combined.jsonl"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pipeline_base import get_base_dir  # noqa: E402

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

profiles = []
with open(f'{BASE}/_parsed/mc_pom_combined.jsonl') as f:
    for line in f:
        rec = json.loads(line)
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
            'gender': extract_gender(rec.get('brand_division', ''), rec.get('department', '')),
            'item_type': rec.get('item_type', ''),
            'category': rec.get('category', ''),
            'department_raw': rec.get('department', ''),
            'brand_division': rec.get('brand_division', ''),
            'design_type': rec.get('design_type', ''),
            'description': rec.get('description', ''),
            'has_mc_pom': has_mc_pom,
            'mc_poms': mc_poms,
            'sizes': sorted(all_sizes),
            'body_types': sorted(body_types),
        })

output = {
    'source': 'mc_pom_combined.jsonl',
    'total': len(profiles),
    'with_mc_pom': sum(1 for p in profiles if p['has_mc_pom']),
    'profiles': profiles
}

out_path = f'{BASE}/measurement_profiles_union.json'
with open(out_path, 'w') as f:
    json.dump(output, f, ensure_ascii=False)
print(f"Built {len(profiles)} profiles ({output['with_mc_pom']} with mc_pom)")
print(f"Saved to {out_path}")
