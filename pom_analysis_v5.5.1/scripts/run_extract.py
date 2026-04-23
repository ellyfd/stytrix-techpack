"""
通用 PDF → mc_pom 萃取腳本。

用法：
  python run_extract.py 2026          ← 萃取 2026 所有子資料夾
  python run_extract.py 2025          ← 萃取 2025 所有子資料夾
  python run_extract.py 2024          ← 萃取 2024 所有子資料夾
  python run_extract.py 2025 FA25     ← 只萃取 2025/FA25
  python run_extract.py 2026 5 SP27   ← 只萃取 2026/5 和 2026/SP27

輸出：_parsed/mc_pom_{year}.jsonl（append 模式，resume-safe）

取代舊版：
  - run_extract_new.py（2026 專用，已刪）
  - run_extract_2025_seasonal.py（2025 季節專用，已刪）
"""
import json, os, sys, time, re

# ─── extract_techpack 位置 ───
# 先找同層，再找 session 根目錄
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for candidate in [
    SCRIPT_DIR,
    os.path.join(SCRIPT_DIR, '..'),
    os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR))),  # session root
]:
    et_path = os.path.join(candidate, 'extract_techpack.py')
    if os.path.exists(et_path):
        sys.path.insert(0, candidate)
        break
from extract_techpack import extract

# ─── 路徑 ───
BASE = os.path.join(os.path.dirname(SCRIPT_DIR), '..')  # → ONY/
BASE = os.path.normpath(BASE)
PARSED = os.path.join(BASE, '_parsed')
MAX_SECONDS = 540  # 9 分鐘安全線

# ─── 參數 ───
if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

year = sys.argv[1]
filter_folders = sys.argv[2:] if len(sys.argv) > 2 else None

year_dir = os.path.join(BASE, year)
if not os.path.isdir(year_dir):
    print(f"❌ 找不到年份資料夾：{year_dir}")
    sys.exit(1)

output_file = os.path.join(PARSED, f'mc_pom_{year}.jsonl')
print(f"年份：{year}")
print(f"輸出：{output_file}")

# ─── Design number 擷取 ───
DN_RE = re.compile(r'D\d{4,6}')

def extract_design_from_path(fpath):
    """從路徑中找 D-number。"""
    for part in reversed(fpath.replace('\\', '/').split('/')):
        m = DN_RE.search(part)
        if m:
            return m.group(0)
    return ''

# ─── 已處理清單（resume-safe）───
done_files = set()
if os.path.exists(output_file):
    with open(output_file) as f:
        for line in f:
            d = json.loads(line)
            done_files.add(d.get('_source_file', ''))
print(f"已處理：{len(done_files)} 筆")

# ─── 收集 PDF ───
pdf_list = []

subfolders = sorted(os.listdir(year_dir))
if filter_folders:
    subfolders = [s for s in subfolders if s in filter_folders]

for subfolder in subfolders:
    sub_path = os.path.join(year_dir, subfolder)
    if not os.path.isdir(sub_path):
        continue
    # 遞迴掃描（處理巢狀資料夾如季節內分 design）
    for root, dirs, files in os.walk(sub_path):
        for fname in sorted(files):
            if fname.lower().endswith('.pdf'):
                pdf_list.append((subfolder, fname, os.path.join(root, fname)))

print(f"找到 PDF：{len(pdf_list)}")

# 去除已處理
remaining = [(m, fn, fp) for m, fn, fp in pdf_list if fn not in done_files]
print(f"待處理：{len(remaining)}")

if not remaining:
    print("✅ 全部已處理，無需動作。")
    sys.exit(0)

# ─── 萃取 ───
t0 = time.time()
processed = 0
mc_count = 0
pom_count = 0
skipped_no_mc = 0

with open(output_file, 'a') as fout:
    for subfolder, fname, fpath in remaining:
        if time.time() - t0 > MAX_SECONDS:
            print(f"\n⏱ 時間到（{MAX_SECONDS}s），已處理 {processed} 筆")
            break

        try:
            result = extract(fpath)
        except Exception as e:
            result = {'_error': str(e), 'mcs': []}

        dn = result.get('design_number') or extract_design_from_path(fpath)

        record = {
            '_source_file': fname,
            '_month': subfolder,
            'design_number': dn,
            'description': result.get('description', ''),
            'brand_division': result.get('brand_division', ''),
            'department': result.get('department', ''),
            'category': result.get('bom_category', ''),
            'sub_category': result.get('sub_category', ''),
            'item_type': result.get('item_type', ''),
            'design_type': result.get('design_type', ''),
            'collection': result.get('collection', ''),
            'flow': result.get('flow', ''),
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
            skipped_no_mc += 1
        processed += 1

        if processed % 100 == 0:
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (len(remaining) - processed) / rate if rate > 0 else 0
            print(f"  {processed}/{len(remaining)} | {elapsed:.0f}s | ETA {eta:.0f}s | MC={mc_count} POM={pom_count} | no_mc={skipped_no_mc}")

elapsed = time.time() - t0
print(f"\n✅ 完成：{processed} 筆，{elapsed:.1f}s")
print(f"   有 MC：{processed - skipped_no_mc}，無 MC：{skipped_no_mc}")
print(f"   MC 區塊：{mc_count}，POM 列：{pom_count}")

# ─── 最終統計 ───
total = 0
total_with_mc = 0
with open(output_file) as f:
    for line in f:
        d = json.loads(line)
        total += 1
        if len(d.get('mcs', [])) > 0:
            total_with_mc += 1
pct = total_with_mc / total * 100 if total > 0 else 0
print(f"\n📊 {os.path.basename(output_file)}：{total} 筆，{total_with_mc} 有 MC（{pct:.1f}%）")
