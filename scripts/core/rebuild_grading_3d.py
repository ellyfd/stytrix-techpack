"""
Rebuild grading_patterns.json with 3D keys (Dept_GT|Gender)
aligned with pom_rules bucket format.

Changes from v1 (2D):
  - Key format: Dept_GT|Gender (e.g. RTW_TOP|WOMENS) instead of Gender|GT
  - BABY/TODDLER included (uses KIDS size order: 2T/3T/4T/5T)
  - Fallback: combos with <3 designs fall back to Gender|GT pool
  - 2D backward-compat keys emitted for frontend transition
  - Output key is 'pairs' (not 'steps') to match frontend line 5340
  - _meta field on each combo tracks source (direct/fallback/2d_compat)

Reads:
  - pom_analysis_v5.5.1/data/design_classification_v5.json
  - _parsed/mc_pom_{2024,2025,2026}.jsonl

Outputs:
  - pom_analysis_v5.5.1/data/grading_patterns.json
"""
import json, os, re, sys
from collections import defaultdict, Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pipeline_base import get_base_dir  # noqa: E402

BASE = str(get_base_dir(description=__doc__))
DATA = os.path.join(BASE, 'pom_analysis_v5.5.1', 'data')
PARSED = os.path.join(BASE, '_parsed')

# ─── Load classification ───
with open(os.path.join(DATA, 'design_classification_v5.json')) as f:
    cls_data = json.load(f)
designs_cls = {d['design_id']: d for d in cls_data['designs']}
print(f"Classification loaded: {len(designs_cls)} designs")

# ─── Parse helpers ───
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
                    return int(prefix) + val
                except:
                    pass
            return val
    return None

# ─── Load raw POM values ───
design_pom_values = defaultdict(lambda: defaultdict(dict))

for year in ['2024', '2025', '2026']:
    fpath = os.path.join(PARSED, f'mc_pom_{year}.jsonl')
    if not os.path.exists(fpath):
        continue
    with open(fpath) as f:
        for line in f:
            rec = json.loads(line)
            dn = rec.get('design_number', '')
            if not dn or dn not in designs_cls:
                continue
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

# ─── Size orders ───
SIZE_ORDER_ADULT = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', '1X', '2X', '3X', '4X']
SIZE_ORDER_KIDS = ['2T', '3T', '4T', '5T', 'XS', 'S', 'M', 'L', 'XL']

def get_size_order(gender):
    if gender in ('BABY/TODDLER', 'BOYS', 'GIRLS'):
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

# ─── Group designs ───
MIN_GRADING_N = 3

# 3D: Dept_GT|Gender (matches pom_rules bucket key)
dept_gt_gender_groups = defaultdict(list)
# 2D: Gender|GT (fallback)
gender_gt_groups = defaultdict(list)

for did, cls in designs_cls.items():
    if did in design_pom_values:
        dept_gt_gender_groups[f"{cls['dept']}_{cls['gt']}|{cls['gender']}"].append(did)
        gender_gt_groups[f"{cls['gender']}|{cls['gt']}"].append(did)

print(f"3D groups: {len(dept_gt_gender_groups)}, 2D groups: {len(gender_gt_groups)}")

# ─── Computation helpers ───
def compute_grading_for_dids(dids, gender):
    """Compute per-POM grading deltas for a set of design IDs."""
    size_order = get_size_order(gender)
    pom_gradings = defaultdict(lambda: defaultdict(list))

    for did in dids:
        if did not in design_pom_values:
            continue
        for pom_key, sizes in design_pom_values[did].items():
            if '|' in pom_key:
                continue  # skip non-REGULAR body types
            code = pom_key
            ordered = [(sz, sizes[sz]) for sz in size_order if sz in sizes]
            for i in range(len(ordered) - 1):
                sz1, v1 = ordered[i]
                sz2, v2 = ordered[i + 1]
                delta = round(v2 - v1, 4)
                step = f"{sz1}→{sz2}"
                pom_gradings[code][step].append(delta)
    return pom_gradings

def grading_result(pom_gradings):
    """Convert raw pom_gradings into final result dict."""
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
            meds = [v['median'] for v in step_medians.values()]
            has_inflection = False
            if len(meds) >= 2:
                for i in range(len(meds) - 1):
                    if meds[i] != 0 and abs(meds[i+1] - meds[i]) / max(abs(meds[i]), 0.001) > 0.5:
                        has_inflection = True
                        break
            combo_result[code] = {
                'pairs': step_medians,
                'inflection': has_inflection
            }
    return combo_result

# ─── Build 3D grading with fallback ───
grading = {}
fallback_used = []
direct_count = 0
skipped = []

# Load pom_rules bucket keys for coverage check
pom_rules_idx = os.path.join(BASE, 'pom_rules', '_index.json')
pom_rules_buckets = set()
if os.path.exists(pom_rules_idx):
    with open(pom_rules_idx) as f:
        for b in json.load(f)['buckets']:
            pom_rules_buckets.add(b['bucket'])

for key_3d, dids in sorted(dept_gt_gender_groups.items()):
    gender = key_3d.split('|')[1]
    pg = compute_grading_for_dids(dids, gender)

    if len(pg) >= MIN_GRADING_N:
        result = grading_result(pg)
        if result:
            result['_meta'] = {'n_designs': len(dids), 'source': 'direct'}
            grading[key_3d] = result
            direct_count += 1
    else:
        # Fallback to 2D (Gender|GT)
        dept_gt = key_3d.split('|')[0]
        gt = dept_gt.split('_', 1)[1] if '_' in dept_gt else dept_gt
        fb_key = f"{gender}|{gt}"
        fb_dids = gender_gt_groups.get(fb_key, [])
        fb_pg = compute_grading_for_dids(fb_dids, gender) if fb_dids else {}

        if len(fb_pg) >= MIN_GRADING_N:
            result = grading_result(fb_pg)
            if result:
                result['_meta'] = {
                    'n_designs': len(dids),
                    'source': 'fallback',
                    'fallback_key': fb_key,
                    'fallback_n': len(fb_dids)
                }
                grading[key_3d] = result
                fallback_used.append((key_3d, fb_key, len(dids), len(fb_dids)))
        else:
            skipped.append((key_3d, len(dids)))

# ── 2D backward-compat keys ──
compat_added = 0
for combo_2d, dids in sorted(gender_gt_groups.items()):
    if combo_2d in grading:
        continue  # already exists (unlikely but safe)
    gender = combo_2d.split('|')[0]
    pg = compute_grading_for_dids(dids, gender)
    if len(pg) >= MIN_GRADING_N:
        result = grading_result(pg)
        if result:
            result['_meta'] = {'n_designs': len(dids), 'source': '2d_compat'}
            grading[combo_2d] = result
            compat_added += 1

# ─── Stats ───
total_pom_families = sum(len({k for k in v if k != '_meta'}) for v in grading.values())
inflection_count = sum(1 for v in grading.values() for k, p in v.items() if k != '_meta' and isinstance(p, dict) and p.get('inflection'))
inflection_rate = round(inflection_count / total_pom_families * 100, 1) if total_pom_families > 0 else 0
covered = sum(1 for b in pom_rules_buckets if b in grading)

# ─── Write output ───
out_path = os.path.join(DATA, 'grading_patterns.json')
with open(out_path, 'w') as f:
    json.dump(grading, f, ensure_ascii=False)

print(f"\n=== Results ===")
print(f"  3D direct:   {direct_count}")
print(f"  3D fallback: {len(fallback_used)}")
print(f"  2D compat:   {compat_added}")
print(f"  Total combos: {len(grading)}")
print(f"  POM families: {total_pom_families}")
print(f"  Inflection:   {inflection_rate}%")
print(f"  pom_rules coverage: {covered}/{len(pom_rules_buckets)} buckets")

# Check BABY/TODDLER specifically
baby_keys = [k for k in grading if 'BABY' in k]
print(f"\n  BABY/TODDLER combos: {len(baby_keys)}")
for k in sorted(baby_keys):
    meta = grading[k].get('_meta', {})
    n_poms = len({p for p in grading[k] if p != '_meta'})
    print(f"    {k}: {n_poms} POMs (n={meta.get('n_designs','?')}, {meta.get('source','?')})")

if fallback_used:
    print(f"\n  Fallback details ({len(fallback_used)}):")
    for k3d, fb, n3d, nfb in fallback_used:
        print(f"    {k3d} (n={n3d}) → {fb} (n={nfb})")

if skipped:
    print(f"\n  Skipped (no data even with fallback): {len(skipped)}")
    for k, n in skipped:
        print(f"    {k} (n={n})")

print(f"\n  Output: {out_path}")
