"""
Batch extract MC+POM from 2025 seasonal PDFs (FA25/HO25/SP25/SU25).
Appends to mc_pom_2025.jsonl. Resume-safe.
"""
import json, os, sys, time, re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / 'lib'))
from _pipeline_base import get_base_dir  # noqa: E402
from extract_techpack import extract  # noqa: E402

BASE = str(get_base_dir(description=__doc__))
OUTPUT = os.path.join(BASE, '_parsed/mc_pom_2025.jsonl')
META_FILE = os.path.join(BASE, '_parsed/all_years.jsonl')
MAX_SECONDS = 540

# Load metadata
print("Loading metadata...")
meta_by_file = {}
if os.path.exists(META_FILE):
    with open(META_FILE) as f:
        for line in f:
            d = json.loads(line)
            if d.get('year') == '2025':
                meta_by_file[d['file']] = d['meta']
print(f"  Metadata: {len(meta_by_file)} entries")

# Load already-processed
done_files = set()
if os.path.exists(OUTPUT):
    with open(OUTPUT) as f:
        for line in f:
            d = json.loads(line)
            done_files.add(d.get('_source_file', ''))
print(f"  Already processed: {len(done_files)}")

DN_RE = re.compile(r'D\d{4,6}')

def extract_design_from_path(fpath):
    for part in reversed(fpath.replace('\\', '/').split('/')):
        m = DN_RE.search(part)
        if m:
            return m.group(0)
    return ''

# Collect PDFs from seasonal folders
pdf_list = []
for season in ['FA25', 'HO25', 'SP25', 'SU25']:
    season_dir = os.path.join(BASE, '2025', season)
    if os.path.isdir(season_dir):
        for root, dirs, files in os.walk(season_dir):
            for fname in sorted(files):
                if fname.lower().endswith('.pdf'):
                    pdf_list.append((season, fname, os.path.join(root, fname)))

print(f"Total seasonal PDFs: {len(pdf_list)}")
remaining = [(m, fn, fp) for m, fn, fp in pdf_list if fn not in done_files]
print(f"  Remaining: {len(remaining)}")

t0 = time.time()
processed = 0
mc_count = 0
pom_count = 0
skipped = 0

with open(OUTPUT, 'a') as fout:
    for month, fname, fpath in remaining:
        if time.time() - t0 > MAX_SECONDS:
            print(f"\n⏱ Time limit after {processed} files")
            break

        try:
            result = extract(fpath)
        except Exception as e:
            result = {'_error': str(e), 'mcs': []}

        dn = result.get('design_number') or extract_design_from_path(fpath)
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
        if n_mc > 0:
            mc_count += n_mc
            pom_count += sum(len(mc['poms']) for mc in record['mcs'])
        else:
            skipped += 1
        processed += 1

        if processed % 100 == 0:
            elapsed = time.time() - t0
            rate = processed / elapsed
            eta = (len(remaining) - processed) / rate if rate > 0 else 0
            print(f"  {processed}/{len(remaining)} | {elapsed:.0f}s | MCs={mc_count} POMs={pom_count} | no_mc={skipped}")

elapsed = time.time() - t0
print(f"\n✅ Done: {processed} files in {elapsed:.1f}s")
print(f"   With MC: {processed - skipped}, No MC: {skipped}")
print(f"   MC blocks: {mc_count}, POM rows: {pom_count}")

total = 0
total_with_mc = 0
with open(OUTPUT) as f:
    for line in f:
        d = json.loads(line)
        total += 1
        if len(d.get('mcs', [])) > 0:
            total_with_mc += 1
print(f"\n📊 mc_pom_2025.jsonl: {total} records, {total_with_mc} with MC ({total_with_mc/total*100:.1f}%)")
