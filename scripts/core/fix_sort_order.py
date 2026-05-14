"""
Fix pom_sort_order: enforce canonical zone order based on garment measurement convention.

Upper body (TOP/OUTERWEAR/DRESS):
  領(B) → 肩(C) → 袖籠(D) → 胸(F) → 下擺(I) → 袖(E) → 身長(J) → 下擺高(T)
  → 腰(H) → 口袋(P) → 繩/帶(Q) → 釦(S) → 其他(Z)

Lower body (PANTS/LEGGINGS/SHORTS/SKIRT):
  腰帶(H) → 約克(G) → 門襟(R) → 前後襠(K) → 臀圍(L) → 三角(M)
  → 腿圍(N) → 內長/外長(O) → 下擺高(T) → 口袋(P) → 繩/帶(Q) → 釦(S) → 其他(Z)

Combined (ROMPER_JUMPSUIT/SET/BODYSUIT):
  Upper zones first, then lower zones

Within each zone, sort by median position from raw mc_pom data as tiebreaker.
"""
import json, os, re, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pipeline_base import get_base_dir  # noqa: E402

BASE = str(get_base_dir(description=__doc__))
# 2026-05-13: Pipeline B 斷鏈修復 — Step 3 (reclassify) 已改寫 repo/pom_rules/,
# Step 6 也要對 repo/pom_rules/ 操作 (BASE/pom_rules/ 是空的或舊的).
# design_classification_v5.json + _parsed/mc_pom_*.jsonl 仍從 BASE 讀.
_SCRIPT_DIR_S6 = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT_S6 = os.path.dirname(os.path.dirname(_SCRIPT_DIR_S6))
_POM_RULES_DIR = os.path.join(_REPO_ROOT_S6, 'pom_rules')

# ─── Zone definitions ───
# Each POM code prefix maps to a zone number.
# Different zone numbering for upper vs lower body.

UPPER_ZONES = {
    'B': 10,   # Neck
    'C': 20,   # Shoulder
    'D': 30,   # Armhole
    'F': 40,   # Chest
    'I': 50,   # Hem/Sweep
    'E': 60,   # Sleeve
    'J': 70,   # Body Length
    'T': 80,   # Hem Height / Stitch
    'A': 85,   # Hood (rare, after main body)
    'H': 87,   # Waist (for tops that have waist measurements)
    'G': 88,   # Yoke (upper body yoke)
    'K': 89,   # Rise (rare on upper body)
    'L': 89,   # Hip (rare on upper body)
    'P': 90,   # Pocket
    'Q': 92,   # Cord/Belt/Loop
    'R': 93,   # Fly/Pleat/Rib
    'S': 94,   # Snap/Button
    'M': 95,   # Gusset (rare on upper body)
    'N': 96,   # Leg (rare on upper body)
    'O': 97,   # Inseam (rare on upper body)
    'Z': 99,   # Misc
}

LOWER_ZONES = {
    'H': 10,   # Waist/Waistband
    'G': 15,   # Yoke
    'R': 18,   # Fly/Pleat
    'K': 20,   # Rise (Front/Back)
    'L': 30,   # Hip
    'M': 35,   # Gusset
    'N': 40,   # Leg (Thigh/Knee/Calf/Leg Opening)
    'O': 50,   # Inseam/Outseam
    'T': 55,   # Hem Height
    'P': 60,   # Pocket
    'Q': 65,   # Cord/Belt/Loop
    'S': 70,   # Snap/Button
    'B': 80,   # Neck (rare on lower body)
    'C': 81,   # Shoulder (rare)
    'D': 82,   # Armhole (rare)
    'E': 83,   # Sleeve (rare)
    'F': 84,   # Chest (rare)
    'I': 85,   # Hem/Sweep (secondary)
    'J': 86,   # Length (secondary)
    'A': 90,   # Hood (shouldn't appear)
    'Z': 99,   # Misc
}

# Combined: upper body zones first (offset 0), lower body zones second (offset +100)
# Some codes need special handling for combined garments
COMBINED_UPPER_CODES = {'B', 'C', 'D', 'F', 'I', 'E', 'J', 'A'}
COMBINED_LOWER_CODES = {'H', 'G', 'R', 'K', 'L', 'M', 'N', 'O'}
# T, P, Q, S, Z appear in both — assign based on context

UPPER_GTS = {'TOP', 'OUTERWEAR', 'DRESS'}
LOWER_GTS = {'PANTS', 'LEGGINGS', 'SHORTS', 'SKIRT'}
COMBINED_GTS = {'ROMPER_JUMPSUIT', 'SET', 'BODYSUIT'}

# ─── Sub-zone ordering for specific codes ───
# Within a zone, these codes have a fixed relative order
SUB_ORDER = {
    # Rise: Front before Back
    'K1': 0, 'K6': 1, 'K2': 2, 'K20': 3, 'K19': 4, 'K23': 5,
    # Hip: position first, then measurement
    'L2': 0, 'L12': 1, 'L3': 2, 'L6': 3, 'L8': 4, 'L11': 5,
    'L16': 6, 'L18': 7, 'L19': 8, 'L20': 9,
    # Leg: thigh → knee → calf → leg opening
    'N2': 0, 'N3': 1, 'N4': 2, 'N5': 3, 'N7': 4, 'N6': 5,
    'N8': 6, 'N20': 7, 'N16': 8, 'N15': 9, 'N9': 10, 'N10': 11,
    # Inseam before Outseam
    'O4': 0, 'O3': 1, 'O1': 2,
    # Waist: Height → Straight → Contour → Relaxed → Extended → Min Stretch
    'H1': 0, 'H2': 1, 'H8': 2, 'H9': 3, 'H18': 4, 'H3': 5,
    'H4': 6, 'H20': 7, 'H21': 8,
    # Gusset: Length before Width
    'M1': 0, 'M5': 1, 'M10': 2, 'M13': 3, 'M15': 4,
    # Neck: Width → Front Drop → Back Drop → Stretch
    'B25': 0, 'B1': 1, 'B11': 2, 'B5': 3, 'B7': 4, 'B9': 5,
    'B26': 10, 'B30': 11, 'B29': 12, 'B32': 13, 'B33': 14, 'B34': 15,
    # Shoulder: Width → Slope → Seam Forward
    'C1': 0, 'C3': 1, 'C6': 2, 'C7': 3, 'C10': 4,
    # Armhole: Raglan pos → Raglan → Straight → Strap
    'D20': 0, 'D21': 1, 'D17': 2, 'D18': 3, 'D13': 4,
    'D1': 5, 'D3': 6, 'D4': 7, 'D7': 8, 'D9': 9, 'D25': 10, 'D19': 11,
    # Chest: Position → High Chest → Chest → At Armhole
    'F4': 0, 'F8': 1, 'F6': 2, 'F9': 3, 'F10': 4, 'F11': 5,
    # Sleeve: Length → Bicep → Elbow → Forearm → Opening → Cuff
    'E1': 0, 'E9': 1, 'E11': 2, 'E12': 3, 'E13': 4,
    'E14': 5, 'E15': 6, 'E16': 7, 'E18': 8, 'E19': 9, 'E20': 10, 'E23': 11,
    # Body Length: CF → CB → Side
    'J9': 0, 'J19': 1, 'J4': 2, 'J10': 3, 'J20': 4, 'J21': 5,
    # Hem: Opening Relaxed → Sweep
    'I5': 0, 'I2': 1, 'I6': 2,
    # Hem Height
    'T10': 0, 'T9': 1, 'T21': 2,
}


def get_sort_key(code, region):
    """Return (zone, sub_order, code) for sorting.

    2026-05-14: garment_type 改用 M7 manifest Item 原值 (不是 TOP/PANTS 9 桶),
    所以排序改吃 bucket 的 body_region 欄 ('upper'/'lower'/'combined').
    """
    prefix = code[0]

    if region == 'lower':
        zone = LOWER_ZONES.get(prefix, 99)
    elif region == 'combined':
        # Combined: upper body part → low zone numbers, lower body → high zone numbers
        if prefix in COMBINED_UPPER_CODES:
            zone = UPPER_ZONES.get(prefix, 50)
        elif prefix in COMBINED_LOWER_CODES:
            zone = 100 + LOWER_ZONES.get(prefix, 50)
        else:
            # T, P, Q, S, Z — put after lower body zones
            zone = 200 + LOWER_ZONES.get(prefix, UPPER_ZONES.get(prefix, 99))
    else:
        # 'upper' or unknown → upper-body zone order
        zone = UPPER_ZONES.get(prefix, 99)

    sub = SUB_ORDER.get(code, 50)  # default 50 = middle
    return (zone, sub, code)


# ─── Load raw mc_pom data for within-zone tiebreaking ───
with open(os.path.join(BASE, 'design_classification_v5.json')) as f:
    clf = json.load(f)
design_info = {d['design_id']: d for d in clf['designs']}

# bucket -> pom_code -> [positions]
bucket_pom_pos = defaultdict(lambda: defaultdict(list))

for year in ['2024', '2025', '2026']:
    fpath = os.path.join(BASE, '_parsed/mc_pom_{}.jsonl'.format(year))
    seen = set()
    if not os.path.exists(fpath):
        continue
    with open(fpath) as f:
        for line in f:
            rec = json.loads(line)
            dn = rec.get('design_number', '')
            if dn in seen or not rec.get('mcs'):
                continue
            seen.add(dn)
            info = design_info.get(dn)
            if not info:
                continue
            bucket = info['bucket']
            for mc in rec['mcs']:
                poms = mc.get('poms', [])
                n = len(poms)
                if n < 3:
                    continue
                for i, pom in enumerate(poms):
                    base = pom['POM_Code'].split('.')[0]
                    pos = i / (n - 1) if n > 1 else 0.5
                    bucket_pom_pos[bucket][base].append(pos)
                break

def median(lst):
    lst.sort()
    return lst[len(lst) // 2]

# ─── Patch each bucket file ───
index_path = os.path.join(_POM_RULES_DIR, '_index.json')
with open(index_path) as f:
    idx = json.load(f)

for bucket_info in idx['buckets']:
    fpath = os.path.join(_POM_RULES_DIR, bucket_info['file'])
    with open(fpath) as f:
        data = json.load(f)

    bucket = data['bucket']
    gt = data['garment_type']
    # 2026-05-14: garment_type = M7 manifest Item 原值; 排序吃 body_region 欄
    region = data.get('body_region', 'upper')

    # All POMs in this bucket
    all_poms = set()
    for tier in ['must', 'recommend', 'optional']:
        all_poms.update(data['measurement_rules'].get(tier, {}).keys())
    all_poms.update(data.get('median_values', {}).keys())

    # Sort: primary by zone, secondary by sub_order, tertiary by median position
    pos_lookup = bucket_pom_pos.get(bucket, {})

    def final_sort_key(code):
        zone, sub, _ = get_sort_key(code, region)
        # Use median position as tiebreaker within same zone+sub
        positions = pos_lookup.get(code, [])
        med_pos = median(list(positions)) if len(positions) >= 2 else 0.5
        return (zone, sub, med_pos, code)

    sorted_poms = sorted(all_poms, key=final_sort_key)
    data['pom_sort_order'] = sorted_poms

    with open(fpath, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

print("Fixed sort order for {} buckets".format(len(idx['buckets'])))

# ─── Verify ───
zone_map = {'A': 'Hood', 'B': 'Neck', 'C': 'Shoulder', 'D': 'Armhole', 'E': 'Sleeve',
            'F': 'Chest', 'G': 'Yoke', 'H': 'Waist', 'I': 'Hem', 'J': 'Length',
            'K': 'Rise', 'L': 'Hip', 'M': 'Gusset', 'N': 'Leg', 'O': 'Inseam',
            'P': 'Pocket', 'Q': 'Cord', 'R': 'Fly', 'S': 'Snap', 'T': 'HemHt', 'Z': 'Misc'}

with open(os.path.join(_POM_RULES_DIR, 'pom_names.json')) as f:
    pom_names = json.load(f)

def show_sort(fname, limit=None):
    fp = os.path.join(_POM_RULES_DIR, fname)
    if not os.path.exists(fp):
        print(f"\n=== {fname} (not present, skip) ===")
        return
    with open(fp) as f:
        d = json.load(f)
    gt = d['garment_type']
    print(f"\n=== {fname} (GT={gt}, {len(d['pom_sort_order'])} POMs) ===")
    for i, code in enumerate(d['pom_sort_order']):
        if limit and i >= limit:
            print(f"  ... +{len(d['pom_sort_order'])-limit} more")
            break
        zone = zone_map.get(code[0], '?')
        en = pom_names.get(code, {})
        en = en.get('en', '?')[:40] if isinstance(en, dict) else '?'
      