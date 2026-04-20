"""
Parse L2_Visual_Differentiation_FullAnalysis_修正版.md → data/l2_visual_guide.json

Goal: give /api/analyze and the UI a structured JSON of every L2's
visual feature + AI-ability tier, grouped by L1 code. Also join with
l2_l3_ie/*.json row counts so we have a historical-frequency number
per L2 for dropdown sorting when AI can't decide.

Primary L2 registry (authoritative list of every valid L2 code + its
xlsx name) comes from L2_代號中文對照表.xlsx (L1代碼 / L1名稱 /
L2代碼 / L2名稱 / L3數). Markdown only supplies visual-feature text
that overlays this.

Output shape:
  {
    "version": "v2",
    "l1": {
      "AH": {
        "name": "袖圍",
        "l2": {
          "AH_001": {
            "name": "合袖",               // xlsx canonical (matches l2_l3_ie)
            "display_name": "一般上袖 set-in",  // from markdown if present
            "feature": "袖線在自然肩線,弧形接合",
            "tier": "green",              // green | yellow | red | unknown
            "vs": null,
            "l3_count": 17,               // from registry
            "freq": 698                   // row count in l2_l3_ie
          }, ...
        }
      }, ...
    }
  }

Tier markers in the markdown:
  🟢 → green  (AI 可分)
  🟡 → yellow (需看細節,可能可以)
  🔴 → red    (AI 無法分,需 IE)
"""

import json, re, os, zipfile, datetime
from collections import OrderedDict
from xml.etree import ElementTree as ET

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'

# ------------------------------------------------------------
# 1. Read the L2 code registry (authoritative)
# ------------------------------------------------------------
def read_registry(path='L2_代號中文對照表.xlsx'):
    with zipfile.ZipFile(path) as z:
        with z.open('xl/worksheets/sheet1.xml') as f:
            root = ET.parse(f).getroot()
    def cval(c):
        t = c.get('t')
        if t == 'inlineStr':
            is_el = c.find(f'{NS}is')
            if is_el is not None:
                return ''.join(tt.text or '' for tt in is_el.iter(f'{NS}t'))
        v = c.find(f'{NS}v')
        return v.text if v is not None else ''
    rows = root.findall(f'.//{NS}row')
    out = []
    for i, r in enumerate(rows):
        cells = [cval(c) for c in r.findall(f'{NS}c')]
        if i == 0 or len(cells) < 4: continue
        l1_code, l1_name, l2_code, l2_name = cells[:4]
        l3_count = int(cells[4]) if len(cells) > 4 and str(cells[4]).isdigit() else None
        if not l2_code or not l2_code.startswith(l1_code): continue
        out.append({
            "l1_code": l1_code, "l1_name": l1_name,
            "l2_code": l2_code, "l2_name": l2_name,
            "l3_count": l3_count
        })
    return out

# ------------------------------------------------------------
# 2. Parse markdown for per-L2 feature text
# ------------------------------------------------------------
MD = open('L2_Visual_Differentiation_FullAnalysis_修正版.md', encoding='utf-8').read()
SECTION_RE = re.compile(r'^###\s+([A-Z]{2})(?:([^\s—]+))?\s*—\s*(\d+)\s+L2\s*(.*)$', re.M)

# Parse L1 sketch definitions from sister doc. Table format:
#   | L1 | 部位名稱 | L2 數 | Sketch 上的視覺定義 |
#   | AE | 袖孔 | 9 | Sketch 上**無袖/背心**款式...↔ AH... |
L1_DEF_PATH = 'L1_部位定義_Sketch視覺指引.md'
l1_sketch_defs = {}
if os.path.exists(L1_DEF_PATH):
    L1_MD = open(L1_DEF_PATH, encoding='utf-8').read()
    L1_ROW_RE = re.compile(r'^\|\s*([A-Z]{2})\s*\|\s*[^|]+?\s*\|\s*\d+\s*\|\s*(.+?)\s*\|\s*$', re.M)
    for m in L1_ROW_RE.finditer(L1_MD):
        l1_sketch_defs[m.group(1)] = m.group(2).strip()

def tier_from_emoji(cell):
    if '🟢' in cell: return 'green'
    if '🟡' in cell: return 'yellow'
    if '🔴' in cell: return 'red'
    return 'unknown'

def vs_from_cell(cell):
    m = re.search(r'vs\s+(\d{3})', cell)
    return m.group(1) if m else None

def strip_md(s):
    s = re.sub(r'\*+([^*]+)\*+', r'\1', s)
    return s.strip()

md_features = {}  # l2_code -> {display_name, feature, tier, vs}
sections = list(SECTION_RE.finditer(MD))
for i, m in enumerate(sections):
    code = m.group(1)
    start = m.end()
    end = sections[i+1].start() if i+1 < len(sections) else len(MD)
    body = MD[start:end]
    # 修正版 tables use 5 columns: | code | name | L3_count | feature | tier |
    row_re = re.compile(rf'^\|\s*({code}_\d{{3}})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|\n]+?)\s*\|', re.M)
    for row in row_re.finditer(body):
        l2_code = row.group(1)
        md_features[l2_code] = {
            "display_name": strip_md(row.group(2)),
            "feature": strip_md(row.group(4)),
            "tier": tier_from_emoji(row.group(5)),
            "vs": vs_from_cell(row.group(5)),
        }

# ------------------------------------------------------------
# 3. Read xlsx row-count frequency from l2_l3_ie/*.json
# ------------------------------------------------------------
def freq_for(l1_code):
    path = f'l2_l3_ie/{l1_code}.json'
    if not os.path.exists(path): return {}
    ie = json.load(open(path, encoding='utf-8'))
    freq = {}
    for fk in ('knit', 'woven'):
        for l2 in ie.get(fk, []):
            name = l2.get('l2'); total = 0
            for sh in l2.get('shapes', []):
                for method in sh.get('methods', []):
                    total += len(method.get('steps', []))
            freq[name] = freq.get(name, 0) + total
    return freq

# ------------------------------------------------------------
# 4. Merge all three sources
# ------------------------------------------------------------
registry = read_registry()
l1_data = OrderedDict()
for row in registry:
    l1c = row['l1_code']
    if l1c not in l1_data:
        l1_data[l1c] = {
            "name": row['l1_name'],
            "sketch_def": l1_sketch_defs.get(l1c, ""),
            "l2": OrderedDict(),
        }
    entry = {
        "name": row['l2_name'],
        "l3_count": row['l3_count'],
    }
    md = md_features.get(row['l2_code'])
    if md:
        entry.update({
            "display_name": md['display_name'],
            "feature": md['feature'],
            "tier": md['tier'],
            "vs": md['vs'],
            "source": "registry+markdown",
        })
    else:
        entry.update({
            "display_name": row['l2_name'],
            "feature": "",
            "tier": "unknown",
            "vs": None,
            "source": "registry",
        })
    l1_data[l1c]['l2'][row['l2_code']] = entry

# Attach freq by matching registry name against xlsx L2 names in l2_l3_ie.
for l1_code, info in l1_data.items():
    freq = freq_for(l1_code)
    for l2_code, entry in info['l2'].items():
        entry['freq'] = freq.get(entry['name'], 0)

# ------------------------------------------------------------
# 5. Write output
# ------------------------------------------------------------
out = {
    "version": "v2",
    "created": datetime.date.today().isoformat(),
    "sources": {
        "registry": "L2_代號中文對照表.xlsx (283 L2s, authoritative)",
        "l1_sketch_def": "L1_部位定義_Sketch視覺指引.md (per-L1 sketch visual definition + sibling contrasts)",
        "markdown": "L2_Visual_Differentiation_FullAnalysis_修正版.md (per-L2 visual features overlay)",
        "freq": "l2_l3_ie/*.json row counts (historical frequency)"
    },
    "tier_rules": {
        "green":   "AI 可直接用視覺判定",
        "yellow":  "需看細節但有望可行",
        "red":     "AI 無法從 sketch 判定,需 IE 文字或歷史資料補足",
        "unknown": "報告未標註特徵,僅有 registry 基本資訊"
    },
    "l1": l1_data,
}
os.makedirs('data', exist_ok=True)
with open('data/l2_visual_guide.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

total_l2 = sum(len(v['l2']) for v in l1_data.values())
with_feat = sum(1 for v in l1_data.values() for l2 in v['l2'].values() if l2.get('feature'))
by_tier = {'green':0,'yellow':0,'red':0,'unknown':0}
for v in l1_data.values():
    for l2 in v['l2'].values():
        by_tier[l2['tier']] = by_tier.get(l2['tier'],0) + 1
print(f'L1 sections: {len(l1_data)}')
print(f'L2 entries (registry): {total_l2}')
print(f'  with markdown feature text: {with_feat}')
print(f'  tier breakdown: {by_tier}')
print(f'Output: data/l2_visual_guide.json ({os.path.getsize("data/l2_visual_guide.json")/1024:.1f} KB)')

