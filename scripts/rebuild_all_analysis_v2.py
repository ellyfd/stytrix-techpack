"""
Rebuild ALL 6 analysis outputs using v5.5.1 classification (10 GT system).
Reads from:
  - design_classification_v5.json (1,056 classified designs)
  - measurement_profiles_union.json (MC+POM data)
  - pom_rules/*.json (bucket rules)
  - zone_construction_analysis_v2_1.json (construction data)
  - mc_pom_{2024,2025,2026}.jsonl (raw tolerance/grading)

Outputs (all to _parsed/):
  ① gender_gt_pom_rules.json
  ② grading_patterns.json
  ③ bodytype_variance.json
  ④ client_rules.json
  ⑤ all_designs_gt_it_classification.json
  ⑥ construction_bridge_v6.json
"""
import json, os, re, math, sys
from collections import defaultdict, Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pipeline_base import get_base_dir  # noqa: E402

BASE = str(get_base_dir(description=__doc__))
PARSED = os.path.join(BASE, '_parsed')

# ─── Load classification ───
with open(os.path.join(BASE, 'design_classification_v5.json')) as f:
    cls_data = json.load(f)
designs_cls = {d['design_id']: d for d in cls_data['designs']}
print(f"Classification loaded: {len(designs_cls)} designs")

# ─── Load profiles ───
with open(os.path.join(BASE, 'measurement_profiles_union.json')) as f:
    prof_data = json.load(f)
profiles_by_id = {}
for p in prof_data['profiles']:
    if p.get('has_mc_pom'):
        profiles_by_id[p['design_id']] = p
print(f"Profiles loaded: {len(profiles_by_id)} with MC+POM")

# ─── Load raw mc_pom for grading/tolerance ───
FRAC_RE = re.compile(r'(\d+)\s*[⁄/]\s*(\d+)')
CENTRIC8_RE = re.compile(r'^(\d+)\s*[⁄/]\s*(\d+)\s+(\d+)$')
VALID_DENOMS = {2, 4, 8, 16, 32}

def parse_val(s):
    if not s or s in ('-', '', 'N/A'):
        return None
    s = str(s).strip()
    if re.search(r'[a-zA-Z]', s):
        return None
    try:
        return float(s)
    except:
        pass
    s2 = s.replace('\u2044', '/')
    m8 = CENTRIC8_RE.match(s2)
    if m8:
        num, whole, den = int(m8.group(1)), int(m8.group(2)), int(m8.group(3))
        if den in VALID_DENOMS and num < den and whole > num:
            return whole + num / den
    m = FRAC_RE.search(s2)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        if den in VALID_DENOMS and den > 0:
            val = num / den
            prefix = s2[:m.start()].strip()
            if prefix:
                try:
                    whole = int(prefix)
                    return whole + val
                except:
                    pass
            return val
    return None

# Build per-design POM values: design_id -> pom_code -> {size: value}
design_pom_values = defaultdict(lambda: defaultdict(dict))
design_years = {}

for year in ['2024', '2025', '2026']:
    fpath = os.path.join(PARSED, f'mc_pom_{year}.jsonl')
    if not os.path.exists(fpath):
        continue
    with open(fpath) as f:
        for line in f:
            rec = json.loads(line)
            dn = rec.get('design_number', '')
            if not dn:
                continue
            design_years[dn] = year
            for mc in rec.get('mcs', []):
                bt = (mc.get('body_type', '') or '').upper()
                for pom in mc.get('poms', []):
                    code = pom.get('POM_Code', '').split('.')[0]
                    if not code:
                        continue
                    for sz, val_str in pom.get('sizes', {}).items():
                        v = parse_val(val_str)
                        if v is not None:
                            key = f"{code}|{bt}" if bt and bt not in ('REGULAR', 'MISSY', 'MISSY-R', '') else code
                            design_pom_values[dn][key][sz] = v

print(f"Raw POM values loaded: {len(design_pom_values)} designs")

# ─── Standard size order ───
SIZE_ORDER_ADULT = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', '1X', '2X', '3X', '4X']
SIZE_ORDER_KIDS = ['2T', '3T', '4T', '5T', 'XS', 'S', 'M', 'L', 'XL']
SIZE_ORDER_BABY = ['NB', '0-3 M', '3-6 M', '6-12 M', '12-18 M', '18-24 M', '3M', '6M', '9M', '12M', '18M', '24M']

def get_size_order(gender):
    if gender == 'BABY/TODDLER':
        return SIZE_ORDER_BABY
    elif gender in ('BOYS', 'GIRLS'):
        return SIZE_ORDER_KIDS
    return SIZE_ORDER_ADULT

def median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2

# ═══════════════════════════════════════════════
# ① gender_gt_pom_rules
# ═══════════════════════════════════════════════
print("\n=== ① Building gender_gt_pom_rules ===")

# Group designs by Gender|GT
gender_gt_groups = defaultdict(list)
for did, cls in designs_cls.items():
    if did in profiles_by_id:
        gender_gt_groups[f"{cls['gender']}|{cls['gt']}"].append(did)

gender_gt_rules = {}
for combo, dids in sorted(gender_gt_groups.items()):
    # Collect POM frequency
    pom_counts = Counter()
    pom_values = defaultdict(lambda: defaultdict(list))  # pom -> size -> [values]
    
    for did in dids:
        if did not in design_pom_values:
            continue
        seen_poms = set()
        for key, sizes in design_pom_values[did].items():
            code = key.split('|')[0]  # strip body_type suffix
            seen_poms.add(code)
            for sz, v in sizes.items():
                pom_values[code][sz].append(v)
        for p in seen_poms:
            pom_counts[p] += 1
    
    n = len(dids)
    must = {}
    recommend = {}
    optional = {}
    
    for pom, cnt in pom_counts.items():
        rate = cnt / n if n > 0 else 0
        med_vals = {}
        for sz, vals in pom_values[pom].items():
            m = median(vals)
            if m is not None:
                med_vals[sz] = round(m, 4)
        
        entry = {'rate': round(rate, 3), 'count': cnt, 'median_values': med_vals}
        if rate >= 0.7:
            must[pom] = entry
        elif rate >= 0.3:
            recommend[pom] = entry
        else:
            optional[pom] = entry
    
    gender_gt_rules[combo] = {
        'n': n,
        'must': must,
        'recommend': recommend,
        'optional': optional
    }

# Build median_values groups (Gender|GT|item_type)
median_groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
for did, cls in designs_cls.items():
    if did not in design_pom_values:
        continue
    key = f"{cls['gender']}|{cls['gt']}|{cls['item_type']}"
    for pom_key, sizes in design_pom_values[did].items():
        code = pom_key.split('|')[0]
        for sz, v in sizes.items():
            median_groups[key][code][sz].append(v)

median_values = {}
for group_key, poms in median_groups.items():
    med = {}
    for code, sizes in poms.items():
        med[code] = {sz: round(median(vals), 4) for sz, vals in sizes.items() if median(vals) is not None}
    median_values[group_key] = med

# `_meta.source_brand`: every input profile is filtered to Old Navy upstream
# (see reclassify_and_rebuild.py, ATHLETA excluded), so the entire output is
# ONY-derived. Front-end reads this to flag when a different brand is selected.
out1 = {'_meta': {'source_brand': 'ONY'},
        'gender_gt_rules': gender_gt_rules, 'median_values': median_values}
with open(os.path.join(PARSED, 'gender_gt_pom_rules.json'), 'w') as f:
    json.dump(out1, f, ensure_ascii=False)
print(f"  {len(gender_gt_rules)} combos, {len(median_values)} median groups")

# ═══════════════════════════════════════════════
# ② grading_patterns
# ═══════════════════════════════════════════════
print("\n=== ② Building grading_patterns ===")

# Group by Gender|GT, compute grading (size-to-size deltas)
grading = {}
MIN_GRADING_N = 3  # minimum designs to compute grading

for combo, dids in sorted(gender_gt_groups.items()):
    gender = combo.split('|')[0]
    if gender == 'BABY/TODDLER':
        continue  # Baby sizes are non-numeric, skip
    
    size_order = get_size_order(gender)
    
    # Collect per-POM grading deltas
    pom_gradings = defaultdict(lambda: defaultdict(list))  # pom -> "S→M" -> [delta]
    
    for did in dids:
        if did not in design_pom_values:
            continue
        for pom_key, sizes in design_pom_values[did].items():
            code = pom_key.split('|')[0]
            if '|' in pom_key:
                continue  # skip non-REGULAR body types for grading
            
            # Sort sizes by standard order
            ordered = [(sz, sizes[sz]) for sz in size_order if sz in sizes]
            for i in range(len(ordered) - 1):
                sz1, v1 = ordered[i]
                sz2, v2 = ordered[i + 1]
                delta = round(v2 - v1, 4)
                step = f"{sz1}→{sz2}"
                pom_gradings[code][step].append(delta)
    
    if len(pom_gradings) < MIN_GRADING_N:
        continue
    
    # Compute median grading per POM per step
    combo_result = {}
    for code, steps in pom_gradings.items():
        step_medians = {}
        for step, deltas in steps.items():
            if len(deltas) >= 2:
                step_medians[step] = {
                    'median': round(median(deltas), 4),
                    'n': len(deltas),
                    'min': round(min(deltas), 4),
                    'max': round(max(deltas), 4)
                }
        if step_medians:
            # Check for inflection: is grading consistent across steps?
            meds = [v['median'] for v in step_medians.values()]
            has_inflection = False
            if len(meds) >= 2:
                for i in range(len(meds) - 1):
                    if meds[i] != 0 and abs(meds[i+1] - meds[i]) / max(abs(meds[i]), 0.001) > 0.5:
                        has_inflection = True
                        break
            combo_result[code] = {
                'steps': step_medians,
                'inflection': has_inflection
            }
    
    if combo_result:
        grading[combo] = combo_result

# Compute overall inflection rate
total_pom_families = sum(len(v) for v in grading.values())
inflection_count = sum(1 for v in grading.values() for p in v.values() if p.get('inflection'))
inflection_rate = round(inflection_count / total_pom_families * 100, 1) if total_pom_families > 0 else 0

# `_meta` sibling carries the brand attribution. Composite keys never start
# with `_`, so this doesn't collide with any real Dept_GT|Gender bucket.
grading_out = {'_meta': {'source_brand': 'ONY'}, **grading}
with open(os.path.join(PARSED, 'grading_patterns.json'), 'w') as f:
    json.dump(grading_out, f, ensure_ascii=False)
print(f"  {len(grading)} combos, {total_pom_families} POM families, inflection rate {inflection_rate}%")

# ═══════════════════════════════════════════════
# ③ bodytype_variance
# ═══════════════════════════════════════════════
print("\n=== ③ Building bodytype_variance ===")

# For each Gender|GT, compare REGULAR vs PETITE/PLUS/TALL
bodytype_var = {}

for combo, dids in sorted(gender_gt_groups.items()):
    gender = combo.split('|')[0]
    gt = combo.split('|')[1]
    
    # Collect per-bodytype POM values
    bt_pom_values = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # bt -> pom -> size -> [val]
    
    for did in dids:
        prof = profiles_by_id.get(did)
        if not prof:
            continue
        for mc_pom in prof.get('mc_poms', []):
            bt = (mc_pom.get('body_type', '') or '').upper() or 'REGULAR'
            if bt in ('MISSY', 'MISSY-R', ''):
                bt = 'REGULAR'
            code = mc_pom.get('code', '').split('.')[0]
            if not code:
                continue
            for sz, val_str in mc_pom.get('sizes', {}).items():
                try:
                    v = parse_val(str(val_str))
                except:
                    v = None
                if v is not None:
                    bt_pom_values[bt][code][sz].append(v)
    
    # Compare each non-REGULAR bt vs REGULAR
    regular = bt_pom_values.get('REGULAR', {})
    if not regular:
        continue
    
    for bt in ['PETITE', 'PLUS', 'TALL']:
        bt_data = bt_pom_values.get(bt, {})
        if not bt_data:
            continue
        
        key = f"{combo}|{bt}"
        
        # M size comparison
        m_comparison = {}
        for code in set(regular.keys()) & set(bt_data.keys()):
            reg_m = regular[code].get('M', [])
            bt_m = bt_data[code].get('M', [])
            if reg_m and bt_m:
                reg_med = median(reg_m)
                bt_med = median(bt_m)
                if reg_med is not None and bt_med is not None:
                    m_comparison[code] = {
                        'regular_M': round(reg_med, 4),
                        f'{bt.lower()}_M': round(bt_med, 4),
                        'delta': round(bt_med - reg_med, 4)
                    }
        
        # Grading deltas comparison
        size_order = get_size_order(gender)
        grading_deltas = {}
        for code in set(regular.keys()) & set(bt_data.keys()):
            reg_ordered = {sz: median(regular[code].get(sz, [])) for sz in size_order if regular[code].get(sz)}
            bt_ordered = {sz: median(bt_data[code].get(sz, [])) for sz in size_order if bt_data[code].get(sz)}
            
            reg_sizes = [sz for sz in size_order if sz in reg_ordered and reg_ordered[sz] is not None]
            bt_sizes = [sz for sz in size_order if sz in bt_ordered and bt_ordered[sz] is not None]
            
            reg_grade = []
            for i in range(len(reg_sizes) - 1):
                reg_grade.append(round(reg_ordered[reg_sizes[i+1]] - reg_ordered[reg_sizes[i]], 4))
            bt_grade = []
            for i in range(len(bt_sizes) - 1):
                bt_grade.append(round(bt_ordered[bt_sizes[i+1]] - bt_ordered[bt_sizes[i]], 4))
            
            if reg_grade and bt_grade:
                grading_deltas[code] = {
                    'regular_grading': reg_grade,
                    f'{bt.lower()}_grading': bt_grade,
                    'same_pattern': reg_grade == bt_grade
                }
        
        if m_comparison or grading_deltas:
            bodytype_var[key] = {
                'm_size_comparison': m_comparison,
                'grading_deltas': grading_deltas
            }

bodytype_var_out = {'_meta': {'source_brand': 'ONY'}, **bodytype_var}
with open(os.path.join(PARSED, 'bodytype_variance.json'), 'w') as f:
    json.dump(bodytype_var_out, f, ensure_ascii=False)
print(f"  {len(bodytype_var)} comparisons")

# ═══════════════════════════════════════════════
# ④ client_rules (cross-year comparison)
# ═══════════════════════════════════════════════
print("\n=== ④ Building client_rules ===")

# Group designs by bucket + year
bucket_year = defaultdict(lambda: defaultdict(list))
for did, cls in designs_cls.items():
    if did in design_years and did in design_pom_values:
        year = design_years[did]
        bucket = cls['bucket']
        bucket_year[bucket][year].append(did)

# Find buckets with data in 2+ years
client_rules = {}
for bucket, years in sorted(bucket_year.items()):
    if len(years) < 2:
        continue
    
    year_medians = {}
    for year, dids in sorted(years.items()):
        pom_vals = defaultdict(lambda: defaultdict(list))
        for did in dids:
            for pom_key, sizes in design_pom_values[did].items():
                code = pom_key.split('|')[0]
                if '|' in pom_key:
                    continue
                for sz, v in sizes.items():
                    pom_vals[code][sz].append(v)
        
        year_med = {}
        for code, sizes in pom_vals.items():
            year_med[code] = {sz: round(median(vals), 4) for sz, vals in sizes.items() if median(vals) is not None}
        year_medians[year] = {'n': len(dids), 'medians': year_med}
    
    # Compute drift between earliest and latest year
    yr_sorted = sorted(year_medians.keys())
    if len(yr_sorted) >= 2:
        early = year_medians[yr_sorted[0]]['medians']
        late = year_medians[yr_sorted[-1]]['medians']
        drift = {}
        for code in set(early.keys()) & set(late.keys()):
            for sz in set(early[code].keys()) & set(late[code].keys()):
                d = round(late[code][sz] - early[code][sz], 4)
                if abs(d) > 0.1:  # only flag meaningful drift
                    if code not in drift:
                        drift[code] = {}
                    drift[code][sz] = d
        
        client_rules[bucket] = {
            'years': year_medians,
            'drift': drift,
            'drift_summary': f"{yr_sorted[0]}→{yr_sorted[-1]}: {len(drift)} POMs drifted"
        }

with open(os.path.join(PARSED, 'client_rules.json'), 'w') as f:
    json.dump(client_rules, f, ensure_ascii=False)
print(f"  {len(client_rules)} buckets with multi-year data")

# ═══════════════════════════════════════════════
# ⑤ GT×IT classification (all 12,038 designs)
# ═══════════════════════════════════════════════
print("\n=== ⑤ Building GT×IT classification ===")

# Re-import classifiers from reclassify script logic
import sys
sys.path.insert(0, BASE)

# We'll classify ALL profiles (not just those with MC+POM)
all_designs_cls = {}
for p in prof_data['profiles']:
    did = p['design_id']
    
    # Use existing classification if available
    if did in designs_cls:
        cls = designs_cls[did]
        all_designs_cls[did] = {
            'design_id': did,
            'gt': cls['gt'],
            'item_type': cls['item_type'],
            'gender': cls['gender'],
            'dept': cls['dept'],
            'fabric': cls['fabric'],
            'description': cls.get('description', ''),
            'design_type': cls.get('design_type', ''),
            'brand_division': p.get('brand_division', ''),
            'has_mc_pom': p.get('has_mc_pom', False),
            'category': cls.get('category', ''),
            'department_raw': cls.get('department_raw', '')
        }
    else:
        # Classify unclassified designs using same v5.5.1 logic
        # Inline classifiers for non-MC designs
        brand = (p.get('brand_division') or '').upper()
        if 'ATHLETA' in brand:
            continue
        
        it = (p.get('item_type') or '').upper()
        cat = (p.get('category') or '').upper()
        dept_raw = (p.get('department_raw') or '').upper()
        dt = (p.get('design_type') or '').upper()
        desc = (p.get('description') or '').upper()
        combined = f"{dt} {it} {desc}"
        
        # Simplified GT classification
        gt = 'UNKNOWN'
        if any(k in combined for k in ['ROMPER', 'JUMPSUIT', 'OVERALL', 'ONESIE', 'FOOTED 1PC', 'FOOTED PJ']):
            gt = 'ROMPER_JUMPSUIT'
        elif dt == 'ONE PIECE' or '1PC' in desc or 'ONE PIECE' in desc:
            gt = 'ROMPER_JUMPSUIT'
        elif any(k in combined for k in ['BODYSUIT', 'BODY SUIT']):
            gt = 'BODYSUIT'
        elif 'SET' in dt.split() or it == 'SETS' or 'SET' in desc.split():
            gt = 'SET'
        elif any(k in combined for k in ['DRESS', 'GOWN', 'CAFTAN']):
            gt = 'DRESS'
        elif 'LEGGING' in combined:
            gt = 'LEGGINGS'
        elif any(k in combined for k in ['SHORT', 'SKORT']):
            gt = 'SHORTS'
        elif 'SKIRT' in combined:
            gt = 'SKIRT'
        elif any(k in combined for k in ['PANT', 'JEAN', 'JOGGER', 'CHINO', 'BOTTOM', 'FLARE', 'WIDE LEG']):
            gt = 'PANTS'
        elif any(k in combined for k in ['JACKET', 'HOODIE', 'VEST', 'COAT', 'CARDIGAN', 'PULLOVER', 'PONCHO', 'ANORAK', 'ROBE', 'OUTERWEAR', 'FLEECE', 'FULL ZIP']):
            gt = 'OUTERWEAR'
        elif any(k in combined for k in ['TOP', 'TEE', 'TANK', 'BLOUSE', 'SHIRT', 'POLO', 'HENLEY', 'CAMI', 'TUNIC', 'CROP', 'BRA', 'BIKINI', 'RASHGUARD', 'TANKINI', 'SLEEVE', 'MOCK NECK']):
            gt = 'TOP'
        
        # Dept
        dept = 'RTW'
        if 'SWIM' in it and 'RASHGUARD' not in it:
            dept = 'Swimwear'
        elif 'SLEEP' in it or it == 'SLEEPWEAR/LOUNGE':
            dept = 'Sleepwear'
        elif dept_raw.strip() in ('NFL', 'NBA', 'MISCSPORTS'):
            dept = 'Collaboration'
        elif 'PERFORMANCE' in dept_raw and 'ACTIVE' in dept_raw:
            dept = 'Active'
        elif 'ACTIVE' in dept_raw:
            dept = 'Active'
        elif 'FLEECE' in dept_raw:
            dept = 'Fleece'
        elif 'SLEEP' in dept_raw:
            dept = 'Sleepwear'
        elif cat.startswith('IPSS'):
            dept = 'Active'
        
        # Fabric
        fabric = 'Woven'
        if cat.startswith('IPSS') or cat.startswith('KNITS'):
            fabric = 'Knit'
        elif cat.startswith('DENIM'):
            fabric = 'Denim'
        elif cat.startswith('WOVEN'):
            fabric = 'Woven'
        elif 'KNIT' in dept_raw:
            fabric = 'Knit'
        elif 'DENIM' in dept_raw:
            fabric = 'Denim'
        
        all_designs_cls[did] = {
            'design_id': did,
            'gt': gt,
            'item_type': p.get('item_type', ''),
            'gender': p.get('gender', ''),
            'dept': dept,
            'fabric': fabric,
            'description': p.get('description', ''),
            'design_type': p.get('design_type', ''),
            'brand_division': p.get('brand_division', ''),
            'has_mc_pom': p.get('has_mc_pom', False),
            'category': p.get('category', ''),
            'department_raw': p.get('department_raw', '')
        }

with open(os.path.join(PARSED, 'all_designs_gt_it_classification.json'), 'w') as f:
    json.dump(all_designs_cls, f, ensure_ascii=False)

gt_counts = Counter(d['gt'] for d in all_designs_cls.values())
print(f"  {len(all_designs_cls)} designs classified")
print(f"  GT distribution: {dict(gt_counts.most_common())}")

# ═══════════════════════════════════════════════
# ⑥ construction_bridge
# ═══════════════════════════════════════════════
print("\n=== ⑥ Building construction_bridge ===")

zone_file = os.path.join(PARSED, 'zone_construction_analysis_v2_1.json')
if os.path.exists(zone_file):
    with open(zone_file) as f:
        zone_data = json.load(f)
    
    # Map GT from classification to zone construction data
    # zone_data is keyed by bucket like "womens_active_knit_LEGGINGS"
    gt_zones = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'count': 0, 'methods': Counter()})))
    
    for bucket_key, bucket_data in zone_data.items():
        # Extract GT from bucket key (last segment after last _)
        parts = bucket_key.split('_')
        gt = parts[-1] if parts else 'UNKNOWN'
        
        if isinstance(bucket_data, dict):
            zones = bucket_data.get('zones', bucket_data)
            if isinstance(zones, dict):
                for zone_name, zone_info in zones.items():
                    if isinstance(zone_info, dict):
                        isos = zone_info.get('iso_codes', zone_info.get('isos', {}))
                        if isinstance(isos, dict):
                            for iso, iso_info in isos.items():
                                methods = iso_info.get('methods', {}) if isinstance(iso_info, dict) else {}
                                count = iso_info.get('count', 1) if isinstance(iso_info, dict) else 1
                                gt_zones[gt][zone_name][iso]['count'] += count
                                if isinstance(methods, dict):
                                    for m, c in methods.items():
                                        gt_zones[gt][zone_name][iso]['methods'][m] += c
    
    bridges = {}
    for gt in sorted(gt_zones.keys()):
        zones = {}
        for zone_name in sorted(gt_zones[gt].keys()):
            isos = {}
            for iso, info in sorted(gt_zones[gt][zone_name].items()):
                isos[iso] = {
                    'count': info['count'],
                    'methods': dict(info['methods'].most_common())
                }
            zones[zone_name] = isos
        bridges[gt] = {
            'zones': zones,
            'zone_count': len(zones),
            'iso_count': sum(len(v) for v in zones.values())
        }
    
    bridge_out = {
        'version': 'v6.1',
        'created': '2026-04-21',
        'method': 'zone_construction_analysis + design_classification_v5 (10 GT system)',
        'description': 'Construction bridge for ALL garment types using v5.5.1 classification.',
        'stats': {
            'total_gts': len(bridges),
            'gts': sorted(bridges.keys())
        },
        'bridges': bridges
    }
    
    with open(os.path.join(PARSED, 'construction_bridge_v6.json'), 'w') as f:
        json.dump(bridge_out, f, ensure_ascii=False)
    print(f"  {len(bridges)} GTs with construction data")
else:
    print(f"  WARNING: {zone_file} not found, skipping bridge rebuild")

print("\n=== ALL DONE ===")
