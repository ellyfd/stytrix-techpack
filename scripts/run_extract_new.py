"""
Batch extract MC+POM from new PDFs:
  - 2026/5 (monthly, flat) → append to mc_pom_2026.jsonl
  - 2026/FA26, HO26, SP26, SU26, SP23, SP27 (seasonal, nested) → append to mc_pom_2026.jsonl
Resume-safe: skips already-processed source files.
"""
import json, os, sys, time, re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / 'pom_analysis_v5.5.1' / 'scripts'))
from _pipeline_base import get_base_dir  # noqa: E402
from extract_techpack import extract  # noqa: E402

BASE = str(get_base_dir(description=__doc__))
OUTPUT_2026 = os.path.join(BASE, '_parsed/mc_pom_2026.jsonl')
META_FILE = os.path.join(BASE, '_parsed/all_years.jsonl')
MAX_SECONDS = 540  # 9 min safety

# Load metadata
print("Loading metadata...")
meta_by_file = {}
if os.path.exists(META_FILE):
    with open(META_FILE) as f:
        for line in f:
            d = json.loads(line)
            if d.get('year') == '2026':
                meta_by_file[d['file']] = d['meta']
print(f"  Metadata: {len(meta_by_file)} entries")

# Load already-processed files
done_files = set()
if os.path.exists(OUTPUT_2026):
    with open(OUTPUT_2026) as f:
        for line in f:
            d = json.loads(line)
            done_files.add(d.get('_source_file', ''))
print(f"  Already processed: {len(done_files)}")

# Design number extraction from path/filename
DN_RE = re.compile(r'D\d{4,6}')

def extract_design_from_path(fpath):
    """Try to extract D-number from path components."""
    for part in reversed(fpath.replace('\\', '/').split('/')):
        m = DN_RE.search(part)
        if m:
            return m.group(0)
    return ''

# Collect all new PDFs
pdf_list = []

# 1) 2026/5 (monthly, flat)
month5_dir = os.path.join(BASE, '2026/5')
if os.path.isdir(month5_dir):
    for fname in sorted(os.listdir(month5_dir)):
        if fname.endswith('.pdf'):
            pdf_list.append(('5', fname, os.path.join(month5_dir, fname)))

# 2) 2026 seasonal folders (nested)
for season in ['FA26', 'HO26', 'SP26', 'SU26', 'SP23', 'SP27']:
    season_dir = os.path.join(BASE, '2026', season)
    if os.path.isdir(season_dir):
        for root, dirs, files in os.walk(season_dir):
            for fname in sorted(files):
                if fname.endswith('.pdf'):
                    pdf_list.append((season, fname, os.path.join(root, fname)))

print(f"Total new PDFs found: {len(pdf_list)}")

# Filter out already processed
remaining = [(m, fn, fp) for m, fn, fp in pdf_list if fn not in done_files]
print(f"  Remaining after dedup: {len(remaining)}")

# Process
t0 = time.time()
processed = 0
mc_count = 0
pom_count = 0
skipped_no_mc = 0

with open(OUTPUT_2026, 'a') as fout:
    for month, fname, fpath in remaining:
        if time.time() - t0 > MAX_SECONDS:
            print(f"\n⏱ Time limit reached after {processed} files")
            break

        try:
            result = extract(fpath)
        except Exception as e:
            result = {'_error': str(e), 'mcs': []}

        # Skip PDFs with no MC data (concept PDFs, sketches, etc.)
        if not result.get('mcs'):
            skipped_no_mc += 1
            # Still record it so we don't re-process
            record = {
                '_source_file': fname,
                '_month': month,
                'design_number': result.get('design_number') or extract_design_from_path(fpath),
                'mcs': [],
            }
            if '_error' in result:
                record['_error'] = result['_error']
            fout.write(json.dumps(record, ensure_ascii=False) + '\n')
            processed += 1
            continue

        # Get design number from extraction or path
        dn = result.get('design_number') or extract_design_from_path(fpath)

        # Get metadata
        meta = meta_by_file.get(fname, {})

        record = {
            '_source_file': fname,
            '_month': month,
            'design_number': dn or meta.get('Design Number', ''),
            'description': meta.get('Description', result.get('description', '')),
            'brand_division': meta.get('Brand/Division', result.get('brand_division', '')),
            'department': meta.get('Department', ''),
            'category': meta.get('Category', result.get('bom_category', '')),
            'sub_category': meta.get('Sub-Category', result.get('sub_category', '')),
            'item_type': meta.get('Item Type', result.get('item_type', '')),
            'design_type': meta.get('Design Type', result.get('design_type', '')),
            'fit_camp': meta.get('Fit Camp', ''),
            'collection': meta.get('Collection', result.get('collection', '')),
            'flow': meta.get('Flow', result.get('flow', '')),
            'mcs': result.get('mcs', []),
        }

        if '_error' in result:
            record['_error'] = result['_error']

        fout.write(json.dumps(record, ensure_ascii=False) + '\n')

        n_mc = len(record['mcs'])
        n_pom = sum(len(mc['poms']) for mc in record['mcs'])
        mc_count += n_mc
        pom_count += n_pom
        processed += 1

        if processed % 100 == 0:
            elapsed = time.time() - t0
            rate = processed / elapsed
            eta = (len(remaining) - processed) / rate if rate > 0 else 0
            print(f"  {processed}/{len(remaining)} | {elapsed:.0f}s | ETA {eta:.0f}s | MCs={mc_count} POMs={pom_count} | skipped_no_mc={skipped_no_mc}")

elapsed = time.time() - t0
print(f"\n✅ Done: {processed} files in {elapsed:.1f}s")
print(f"   With MC: {processed - skipped_no_mc}, Skipped (no MC): {skipped_no_mc}")
print(f"   MC blocks: {mc_count}, POM rows: {pom_count}")

# Final stats
total = 0
total_mc = 0
total_with_mc = 0
with open(OUTPUT_2026) as f:
    for line in f:
        d = json.loads(line)
        total += 1
        n = len(d.get('mcs', []))
        total_mc += n
        if n > 0:
            total_with_mc += 1

print(f"\n📊 mc_pom_2026.jsonl: {total} records, {total_with_mc} with MC data ({total_with_mc/total*100:.1f}%)")
