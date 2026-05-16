"""
v5.5.1 — Complete reclassification + pom_rules rebuild.
Changes from v5.5:
  - ATHLETA brand excluded (Old Navy only)
  - Collaboration dept (NFL/NBA/MISCSPORTS)
  - IPSS category → Active (運動專精)
  - Fabric metadata (Knit/Woven/Denim)
Legacy fixes (v5.0-v5.5):
  1. GT=UNKNOWN for swim (1PC/RASHGUARD/BOTTOM), sleep (ONESIE/ROBE), lounge
  2. Maternity is Gender only, not Department
  3. Active priority: PERFORMANCE ACTIVE > ACTIVE > FLEECE > SWIM in mixed dept
  4. LEGGINGS as separate GT (not PANTS)
  5. Centric 8 fraction parsing fix
"""
import json, re, math, os, sys
from collections import defaultdict, Counter
from pathlib import Path

# Pipeline post-step:強制 tier1 POM 進入 measurement_rules.must,跟
# foundational_measurements.enforced 規則一致。這裡 import 同目錄下的模組。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enforce_tier1 import enforce_bucket  # noqa: E402
from _pipeline_base import get_base_dir, mk_item_region  # noqa: E402

# ─── Load ───
BASE = str(get_base_dir(description=__doc__))
with open(os.path.join(BASE, 'measurement_profiles_union.json'), encoding='utf-8') as f:
    pdata = json.load(f)
# Filter: has MC data only (2026-05-11: 拿掉 ATHLETA filter, 開放 ONY 集團全 brand)
# 之前 Old Navy only 是 v5.5 政策, 現在要擴 21 brand 第一步: 把同集團 Centric 8 5 家
# (ONY / GAP / GAP_OUTLET / ATHLETA / BANANA_REPUBLIC) 全進 pom_rules.
profiles = [p for p in pdata['profiles']
            if p.get('has_mc_pom')]
print("Profiles loaded: {} (all Centric 8 brands)".format(len(profiles)))

with open(os.path.join(BASE, 'pom_dictionary.json'), encoding='utf-8') as f:
    pom_dict = json.load(f)

# ─── Load raw tolerance from mc_pom files ───
VALID_DENOMS = {2, 4, 8, 16, 32}
FRAC_RE = re.compile(r'(\d+)\s*[⁄/]\s*(\d+)')

# 2026-05-16: 4 維度分類改 data-driven, 邏輯走 data/source/*_keywords.json
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "lib"))
from resolve_classification import (
    resolve_dept as _resolve_dept_table,
    resolve_fabric as _resolve_fabric_table,
    resolve_gt as _resolve_gt_table,
)

def parse_tol(s):
    """Parse tolerance string → float inches. Only accept fractions & decimals."""
    if not s or not str(s).strip():
        return None
    s = str(s).strip()
    # Reject anything with letters (text labels like Long, Loose, Graded)
    if re.search(r'[a-zA-Z]', s):
        return None
    # Try direct float
    try:
        v = float(s)
        if abs(v) > 5 or v == 0:
            return None  # sentinels (777, 999) or zero
        return v
    except:
        pass
    # Try fraction
    m = FRAC_RE.search(s)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        if den not in VALID_DENOMS or num >= den or den == 0:
            return None
        val = num / den
        if '-' in s:
            val = -val
        return val
    return None

def _tol_display(val):
    """Convert float tolerance to display string like '1/4' or '1/8'."""
    common = {0.125: '1/8', 0.25: '1/4', 0.375: '3/8', 0.5: '1/2',
              0.0625: '1/16', 0.1875: '3/16', 0.3125: '5/16',
              0.4375: '7/16', 0.5625: '9/16', 0.625: '5/8',
              0.75: '3/4', 0.875: '7/8', 1.0: '1'}
    rounded = round(val, 4)
    return common.get(rounded, str(rounded))

# Build raw tolerance lookup: design_id -> pom_code -> {pos, neg}
raw_tol = defaultdict(dict)
for year in ['2024', '2025', '2026']:
    fpath = os.path.join(BASE, '_parsed/mc_pom_{}.jsonl'.format(year))
    if not os.path.exists(fpath):
        continue
    with open(fpath, encoding='utf-8') as f:
        for line in f:
            rec = json.loads(line)
            dn = rec.get('design_number', '')
            for mc in rec.get('mcs', []):
                for pom in mc.get('poms', []):
                    code = pom.get('POM_Code', '').split('.')[0]
                    if not code:
                        continue
                    tol = pom.get('tolerance', {})
                    tp = parse_tol(tol.get('pos', ''))
                    tn = parse_tol(tol.get('neg', ''))
                    if tp is not None or tn is not None:
                        raw_tol[dn][code] = {'pos': tp, 'neg': tn}

print("Raw tolerance loaded: {} designs, {} POM entries".format(
    len(raw_tol), sum(len(v) for v in raw_tol.values())))

# ═══════════════════════════════════════════════
# CLASSIFIERS v3
# ═══════════════════════════════════════════════

def real_dept_v4(p):
    """Department classifier v2 (2026-05-16) — 改 data-driven。
    Canonical enum v2 = 6 個: ACTIVE / RTW / SWIMWEAR / SLEEPWEAR / DENIM / FLEECE
    COLLAB→ACTIVE; MATERNITY→GENDER (resolve_gender 處理)。
    所有 cascade 邏輯走 data/source/dept_keywords.json + data/runtime/dept_lookup_by_subgroup.json。
    """
    return _resolve_dept_table(p)


def infer_fabric(p):
    """Fabric classifier (2026-05-16) — 改 data-driven。
    主路徑 = mk_fabric (M7 列管 W/K); fallback 走 data/source/fabric_keywords.json。
    Canonical enum: Knit / Woven / Denim (Fleece 保留位置, 未來 M7 加才用)
    """
    return _resolve_fabric_table(p)


def real_gt_v2(p):
    """Garment type classifier (2026-05-16) — 改 data-driven。
    主路徑 = M7 manifest_item 原值 (聚陽款式分類); fallback 9 類走 data/source/gt_keywords.json。
    """
    return _resolve_gt_table(p)


def base_code(c):
    return c.split('.')[0] if c else c

def is_valid_pom(c):
    return bool(re.match(r'^[A-Z]{1,2}\d{1,3}$', c))

FRAC_VAL_RE = re.compile(r'(\d+)\s*[⁄/]\s*(\d+)')
# Centric 8 format: "1⁄ 17 2" means 17 + 1/2 = 17.5
# Pattern: numerator ⁄ whole_number denominator
CENTRIC8_RE = re.compile(r'^(\d+)\s*[⁄/]\s*(\d+)\s+(\d+)$')
VALID_FRAC_DENOMS = {2, 4, 8, 16, 32}

def parse_val(s):
    if not s or s in ('-', '', 'N/A'):
        return None
    s = str(s).strip()
    try:
        return float(s)
    except:
        pass
    s2 = s.replace('\u2044', '/')
    # ── Centric 8 format: "1/ 17 2" → num=1, whole=17, den=2 → 17.5 ──
    m = CENTRIC8_RE.match(s2)
    if m:
        num, whole, den = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if den in VALID_FRAC_DENOMS and num < den and whole > num:
            return whole + num / den
    # ── Standard: "14 1/2" → 14.5 ──
    m = re.match(r'^(-?\d+)\s+(\d+)\s*[⁄/]\s*(\d+)$', s2)
    if m:
        w, n, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if d == 0:
            return None
        return w + n / d if w >= 0 else w - n / d
    # ── Pure fraction: "1/4" → 0.25 ──
    m = re.match(r'^(-?\d+)\s*[⁄/]\s*(\d+)$', s2)
    if m:
        n, d = int(m.group(1)), int(m.group(2))
        if d == 0:
            return None
        return n / d
    # ── Fallback: strip quotes ──
    try:
        return float(s.replace('"', '').strip())
    except:
        return None


bucket_profiles = defaultdict(list)
classification_log = []

for p in profiles:
    dept = real_dept_v4(p)
    gt = real_gt_v2(p)
    fabric = infer_fabric(p)
    gender = (p.get('gender') or 'UNKNOWN').upper()
    bucket_key = "{}_{}\u007c{}".format(dept, gt, gender)

    # Extract POM data with raw tolerance
    pom_data = {}
    design_id = p['design_id']
    for mc in p.get('mc_poms', []):
        code = base_code(mc.get('code', ''))
        if not is_valid_pom(code):
            continue
        sizes = mc.get('sizes', {})
        parsed = {}
        for sz, val in sizes.items():
            v = parse_val(val)
            if v is not None:
                parsed[sz] = v
        if parsed:
            # Get tolerance from raw files (higher quality)
            tol_pos = None
            tol_neg = None
            if design_id in raw_tol and code in raw_tol[design_id]:
                tol_pos = raw_tol[design_id][code].get('pos')
                tol_neg = raw_tol[design_id][code].get('neg')
            # Fallback to profile tolerance
            if tol_pos is None and tol_neg is None:
                tol = mc.get('tolerance', {})
                tp = parse_tol(tol.get('pos', ''))
                tn = parse_tol(tol.get('neg', ''))
                if tp is not None:
                    tol_pos = tp
                if tn is not None:
                    tol_neg = tn
            pom_data[code] = {
                'values': parsed,
                'tolerance_pos': tol_pos,
                'tolerance_neg': tol_neg,
                'body_type': mc.get('body_type', '')
            }

    if pom_data:
        bucket_profiles[bucket_key].append({
            'design_id': design_id,
            'pom_data': pom_data,
            'pom_set': set(pom_data.keys()),
            'sizes': p.get('sizes', []),
            'body_types': p.get('body_types', []),
            'brand_division': p.get('brand_division', ''),
            '_client_code': p.get('_client_code', ''),  # 聚陽 canonical brand code
        })

    classification_log.append({
        'design_id': design_id,
        'dept': dept,
        'gt': gt,
        'gender': gender,
        'fabric': fabric,
        'bucket': bucket_key,
        'department_raw': p.get('department_raw', ''),
        'category': p.get('category', ''),
        'item_type': p.get('item_type', ''),
        'design_type': p.get('design_type', ''),
        'description': p.get('description', ''),
        'brand_division': p.get('brand_division', ''),
        '_client_code': p.get('_client_code', ''),  # 聚陽 canonical brand code (餵 bodytype_variance brand 維度)
    })

# ─── Audit ───
total = sum(len(v) for v in bucket_profiles.values())
print("\n=== CLASSIFICATION v4 (v5.5.1) SUMMARY ===")
print("Total designs: {}".format(total))
print("Total buckets: {}".format(len(bucket_profiles)))

# Department distribution
dept_counts = Counter()
for entry in classification_log:
    dept_counts[entry['dept']] += 1
print("\nDepartment distribution:")
for dept, cnt in dept_counts.most_common():
    print("  {}: {}".format(dept, cnt))

# GT distribution
gt_counts = Counter()
for entry in classification_log:
    gt_counts[entry['gt']] += 1
print("\nGT distribution:")
for gt, cnt in gt_counts.most_common():
    print("  {}: {}".format(gt, cnt))

# UNKNOWN check
unknowns = [e for e in classification_log if e['gt'] == 'UNKNOWN']
print("\n=== GT=UNKNOWN: {} ===".format(len(unknowns)))
for u in unknowns[:20]:
    print("  {} | dept_raw={} | it={} | dt={} | desc={}".format(
        u['design_id'], u['department_raw'][:35], u['item_type'][:25],
        u['design_type'][:15], u['description'][:40]))

# Fabric distribution
fab_counts = Counter()
for entry in classification_log:
    fab_counts[entry['fabric']] += 1
print("\nFabric distribution:")
for fab, cnt in fab_counts.most_common():
    print("  {}: {}".format(fab, cnt))

# Collaboration check
collab = [e for e in classification_log if e['dept'] == 'Collaboration']
print("\nCollaboration: {} designs".format(len(collab)))

# Bucket sizes
print("\n=== BUCKETS (sorted by size) ===")
for bucket, designs in sorted(bucket_profiles.items(), key=lambda x: -len(x[1])):
    if len(designs) >= 3:
        print("  {:>4} | {}".format(len(designs), bucket))

# ═══════════════════════════════════════════════
# GENERATE pom_rules/ v5.0
# ═══════════════════════════════════════════════
import statistics

# 2026-05-11: OUT_DIR 改寫到本 repo (stytrix-techpack/pom_rules/),不再寫 BASE (聚陽 ONY 端)
# 統一最終位置 — 前端 fetch + git 版控都在 stytrix-techpack/pom_rules/
# 舊 BASE/pom_rules/ 可以清掉 (build 中介,不需保留)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))  # stytrix-techpack/
OUT_DIR = os.path.join(_REPO_ROOT, 'pom_rules')
os.makedirs(OUT_DIR, exist_ok=True)
print(f"[reclassify] OUT_DIR = {OUT_DIR}")

# Clear old files
for f in os.listdir(OUT_DIR):
    (os.path.isdir(os.path.join(OUT_DIR, f)) or os.remove(os.path.join(OUT_DIR, f)))

SIZE_ORDER = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', '2XL', '3XL',
              '0', '2', '4', '6', '8', '10', '12', '14', '16', '18', '20',
              '2T', '3T', '4T', '5T',
              '4/5', '6/7', '8', '10/12', '14/16',
              '12M', '18M', '24M']

def size_sort_key(s):
    try:
        return SIZE_ORDER.index(s)
    except ValueError:
        return 999

def bucket_to_filename(bucket):
    dept, rest = bucket.split('_', 1)
    gt_gender = rest.split('|')
    gt = gt_gender[0].lower()
    gender = gt_gender[1].lower() if len(gt_gender) > 1 else 'unknown'
    # Sanitize: space + / → _ for filesystem safety.
    # gt 現在是 M7 manifest Item 原值 (含空格與 /, 如 "pull on pants" / "blouse/shirts"),
    # gender 可能是 baby/toddler — 兩者都要清掉 / 與空格.
    gender = gender.replace('/', '_').replace(' ', '_')
    gt = gt.replace('/', '_').replace(' ', '_')
    return "{}_{}_{}".format(gender, dept.lower(), gt)

index_entries = []

for bucket, designs in sorted(bucket_profiles.items(), key=lambda x: -len(x[1])):
    n = len(designs)
    if n < 3:
        continue

    parts = bucket.split('_', 1)
    dept = parts[0]
    gt_gender = parts[1].split('|')
    gt = gt_gender[0]
    gender = gt_gender[1] if len(gt_gender) > 1 else 'UNKNOWN'

    # POM frequency
    pom_freq = Counter()
    for d in designs:
        for p in d['pom_set']:
            pom_freq[p] += 1

    # Size range
    all_sizes = set()
    for d in designs:
        if isinstance(d.get('sizes'), list):
            all_sizes.update(d['sizes'])
        for pom_code, pom_info in d['pom_data'].items():
            all_sizes.update(pom_info['values'].keys())
    sorted_sizes = sorted(all_sizes, key=size_sort_key)

    # measurement_rules
    must_poms = {}
    rec_poms = {}
    opt_poms = {}
    for pom_code, cnt in pom_freq.items():
        rate = cnt / n
        # Tolerance for this POM across designs
        tol_vals = []
        for d in designs:
            if pom_code in d['pom_data']:
                tp = d['pom_data'][pom_code].get('tolerance_pos')
                tn = d['pom_data'][pom_code].get('tolerance_neg')
                if tp is not None:
                    tol_vals.append(abs(tp))
                elif tn is not None:
                    tol_vals.append(abs(tn))

        tol_info = {}
        if tol_vals:
            tol_counter = Counter(round(t, 4) for t in tol_vals)
            top_tol = tol_counter.most_common(1)[0]
            tol_info = {
                'standard': round(top_tol[0], 4),
                'display': _tol_display(top_tol[0]),
                'dominance_pct': round(top_tol[1] / len(tol_vals) * 100, 1),
                'n': len(tol_vals)
            }

        entry = {
            'rate': round(rate, 3),
            'count': cnt,
        }
        if tol_info:
            entry['tolerance'] = tol_info

        if rate >= 0.70:
            must_poms[pom_code] = entry
        elif rate >= 0.50:
            rec_poms[pom_code] = entry
        elif rate >= 0.25:
            opt_poms[pom_code] = entry

    # median_values per POM
    median_values = {}
    for pom_code in pom_freq:
        size_values = defaultdict(list)
        for d in designs:
            if pom_code in d['pom_data']:
                for sz, val in d['pom_data'][pom_code]['values'].items():
                    if val > 0:
                        size_values[sz].append(val)
        if size_values:
            size_medians = {}
            for sz in sorted(size_values.keys(), key=size_sort_key):
                vals = size_values[sz]
                if len(vals) >= 2:
                    size_medians[sz] = round(statistics.median(vals), 3)
            if size_medians:
                median_values[pom_code] = {'size_medians': size_medians}

    # grading_rules per POM
    grading_rules = {}
    for pom_code in pom_freq:
        increments = []
        for d in designs:
            if pom_code not in d['pom_data']:
                continue
            vals = d['pom_data'][pom_code]['values']
            sz_list = sorted(vals.keys(), key=size_sort_key)
            for i in range(len(sz_list) - 1):
                s1, s2 = sz_list[i], sz_list[i + 1]
                diff = vals[s2] - vals[s1]
                if abs(diff) < 10:  # reasonable increment
                    increments.append(diff)
        if increments:
            grading_rules[pom_code] = {
                'typical_increment': round(statistics.median(increments), 3),
                'n_pairs': len(increments)
            }

    # tolerance_standards per POM
    tolerance_standards = {}
    for pom_code in pom_freq:
        tol_vals = []
        for d in designs:
            if pom_code in d['pom_data']:
                tp = d['pom_data'][pom_code].get('tolerance_pos')
                tn = d['pom_data'][pom_code].get('tolerance_neg')
                if tp is not None:
                    tol_vals.append(abs(tp))
                elif tn is not None:
                    tol_vals.append(abs(tn))
        if tol_vals:
            tol_counter = Counter(round(t, 4) for t in tol_vals)
            top = tol_counter.most_common(1)[0]
            tolerance_standards[pom_code] = {
                'standard': round(top[0], 4),
                'display': _tol_display(top[0]),
                'dominance_pct': round(top[1] / len(tol_vals) * 100, 1),
                'n': len(tol_vals)
            }

    # 2026-05-11: source_brand 動態化 — ATHLETA filter 拿掉後 bucket 可能含 ONY/GAP/ATH/BRFS 混合
    # 取最頻繁的 brand 當主要,並列出全部分布 (frontend 可選顯示 single vs multi-source)
    # 2026-05-14: brand 維度走聚陽 canonical — _client_code 是 adapter 從 M7列管 注入的
    # 3-letter code (DKS/ONY/GAP/KOH/TGT…, v9 實測 100% 覆蓋), 直接對齊 brands.json dropdown。
    # 舊版硬解 brand_division + bd[:10] 截斷成 'DSG WOMENS' 跟 brands.json 對不上 (DKS 找不到資料 bug)。
    brand_counts = Counter()
    for d in designs:
        cc = (d.get('_client_code') or '').strip().upper()
        if cc:
            brand_counts[cc] += 1
            continue
        # fallback: _client_code 空 (EIDH 不在 M7列管, v9 實測 0%) → 從 brand_division 粗推
        bd = (d.get('brand_division') or '').strip().upper()
        if 'OLD NAVY' in bd: brand_counts['ONY'] += 1
        elif 'GAP' in bd: brand_counts['GAP'] += 1
        elif 'ATHLETA' in bd: brand_counts['ATH'] += 1
        elif 'BANANA' in bd or bd.startswith('BRFS'): brand_counts['BR'] += 1
        elif bd: brand_counts[bd[:10]] += 1
        else: brand_counts['UNKNOWN'] += 1
    primary_brand = brand_counts.most_common(1)[0][0] if brand_counts else 'UNKNOWN'

    bucket_data = {
        'bucket': bucket,
        # Brand 分布 (2026-05-11 改成 dict): primary 是樣本最多的 brand,
        # distribution 是完整分布。前端用這個告訴 user 該 bucket 樣本來自哪些 brand。
        'source_brand': primary_brand,
        'source_brand_distribution': dict(brand_counts.most_common()),
        'department': dept,
        'garment_type': gt,
        # body_region: upper/lower/combined — 只給 POM 排序 + tier1 預設用,
        # 不是 garment_type 本身 (garment_type = M7 manifest Item 原值)
        'body_region': mk_item_region(gt),
        'gender': gender,
        'n': n,
        'size_range': sorted_sizes,
        'measurement_rules': {
            'must': must_poms,
            'recommend': rec_poms,
            'optional': opt_poms,
        },
        'median_values': median_values,
        'grading_rules': grading_rules,
        'tolerance_standards': tolerance_standards,
    }

    # Enforce foundational ⊂ must before persisting. enforce_bucket adds
    # foundational_measurements (based on GT) if missing, then guarantees
    # every tier1 POM is in mr.must (moving from recommend/optional or
    # inserting an absent placeholder).
    enforce_bucket(bucket_data)

    fname = bucket_to_filename(bucket) + '.json'
    fpath = os.path.join(OUT_DIR, fname)
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(bucket_data, f, indent=2, ensure_ascii=False)

    size_kb = round(os.path.getsize(fpath) / 1024, 1)
    index_entries.append({
        'bucket': bucket,
        'file': fname,
        'n': n,
        'department': dept,
        'garment_type': gt,
        'body_region': bucket_data['body_region'],
        'gender': gender,
        'pom_count': len(pom_freq),
        'must_count': len(bucket_data['measurement_rules']['must']),
        'size_kb': size_kb,
    })

# Save _index.json
# 聚合所有 bucket 的 source_brand_distribution → 全域 brand codes,frontend
# 用這個 array 來判斷 user 選的 brand 是否有 POM 資料(取代 2026-05-11 之前用
# 單一字串 source_brand 等值比對 — 那條路徑在多 brand 合併後沒辦法跟 brands.json
# dropdown code 對齊,所有 brand 都會被擋下)。
_global_brand_counts = Counter()
for _ie in index_entries:
    _bfile = os.path.join(OUT_DIR, _ie['file'])
    try:
        with open(_bfile, 'r', encoding='utf-8') as _fp:
            _bd = json.load(_fp)
    except (OSError, json.JSONDecodeError):
        continue
    for _code, _cnt in (_bd.get('source_brand_distribution') or {}).items():
        _global_brand_counts[_code] += _cnt
# 排序 by count DESC,drop UNKNOWN(無 brand 標的 design 雜訊,不該出現在 dropdown 對照)
_source_brand_codes = [c for c, _ in _global_brand_counts.most_common() if c != 'UNKNOWN']

index_data = {
    '_meta': {
        'version': '5.5.1',
        'source_brand': 'Centric 8 (ONY/GAP/ATHLETA/BRFS)',  # 2026-05-11: 拿掉 ATHLETA filter;human-readable 顯示用
        'source_brand_codes': _source_brand_codes,  # 2026-05-12: frontend brand-match gate 用 — 對齊 brands.json dropdown code
        'source': '{} designs x mc_pom_2024/2025/2026 (all Centric 8 brands)'.format(total),
        'date': '2026-05-11',
        'departments': sorted(set(e['department'] for e in index_entries)),
        'filter_chain': 'Brand -> Fabric -> Department -> Gender -> GT -> Item Type',
        'classifiers': 'real_dept_v4 + real_gt_v2 + infer_fabric',
        'changes_v551': [
            'ATHLETA brand excluded',
            'Collaboration dept (NFL/NBA/MISCSPORTS)',
            'IPSS category → Active',
            'Fabric metadata (Knit/Woven/Denim)',
            'Maternity is Gender only (not Department)',
        ],
    },
    'buckets': sorted(index_entries, key=lambda x: -x['n'])
}

with open(os.path.join(OUT_DIR, '_index.json'), 'w', encoding='utf-8') as f:
    json.dump(index_data, f, indent=2, ensure_ascii=False)

# Save pom_names.json
with open(os.path.join(OUT_DIR, 'pom_names.json'), 'w', encoding='utf-8') as f:
    json.dump(pom_dict, f, indent=2, ensure_ascii=False)

# Save classification log
with open(os.path.join(BASE, 'design_classification_v5.json'), 'w', encoding='utf-8') as f:
    json.dump({
        'version': '5.5.1',
        'classifiers': 'real_dept_v4 + real_gt_v2 + infer_fabric',
        'total': len(classification_log),
        'designs': classification_log,
    }, f, indent=2, ensure_ascii=False)

print("\n=== OUTPUT ===")
print("pom_rules/ files: {}".format(len(index_entries)))
total_kb = sum(e['size_kb'] for e in index_entries)
print("Total size: {:.0f} KB".format(total_kb))
print("design_classification_v5.json saved")
print("Done!")
