"""
Parse L2_Visual_Differentiation_FullAnalysis.md → data/l2_visual_guide.json

Goal: give /api/analyze and the UI a structured JSON of every L2's
visual feature + AI-ability tier, grouped by L1 code. Also join with
l2_l3_ie/*.json row counts so we have a historical-frequency number
per L2 for dropdown sorting when AI can't decide (user said: "歷史資料,
但不是 ISO 的").

Output shape:
  {
    "version": "v1",
    "l1": {
      "AH": {
        "name": "袖圍",
        "section_note": "AI 可完全區分",
        "l2": {
          "AH_001": {
            "name": "一般上袖 set-in",
            "feature": "袖線在自然肩線,弧形接合",
            "tier": "green",        // green | yellow | red | unknown
            "vs": null              // "005" if '🔴 vs 005' flagged
          },
          ...
        }
      },
      ...
    }
  }

Tier markers in the markdown:
  🟢 → green  (AI 可分)
  🟡 → yellow (需看細節,可能可以)
  🔴 → red    (AI 無法分,需 IE)
"""

import json, re, os, glob
from collections import OrderedDict

MD = open('L2_Visual_Differentiation_FullAnalysis.md', encoding='utf-8').read()

# Scan L1 section headers: "### CODE(Chinese name)— N L2 [suffix]"
SECTION_RE = re.compile(r'^###\s+([A-Z]{2})(?:([^\s—]+))?\s*—\s*(\d+)\s+L2\s*(.*)$', re.M)

def tier_from_emoji(cell):
    if '🟢' in cell: return 'green'
    if '🟡' in cell: return 'yellow'
    if '🔴' in cell: return 'red'
    return 'unknown'

def vs_from_cell(cell):
    m = re.search(r'vs\s+(\d{3})', cell)
    return m.group(1) if m else None

def strip_md(s):
    # Remove **bold**, *italic*, extra whitespace
    s = re.sub(r'\*+([^*]+)\*+', r'\1', s)
    return s.strip()

# Parse sections
sections = list(SECTION_RE.finditer(MD))
l1_data = OrderedDict()

for i, m in enumerate(sections):
    code = m.group(1)
    cn_raw = m.group(2) or ''
    cn = cn_raw.strip('()()')
    header_suffix = m.group(4).strip()
    # Section body: from end of this header line to start of next section header
    start = m.end()
    end = sections[i+1].start() if i+1 < len(sections) else len(MD)
    body = MD[start:end]

    entries = OrderedDict()
    # Match rows like: | AH_001 | 一般上袖 set-in | 袖線... | 🟢 |
    row_re = re.compile(rf'^\|\s*({code}_\d{{3}})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|\n]+?)\s*\|', re.M)
    for row in row_re.finditer(body):
        l2_code = row.group(1)
        name = strip_md(row.group(2))
        feature = strip_md(row.group(3))
        tier_cell = row.group(4).strip()
        entries[l2_code] = {
            "name": name,
            "feature": feature,
            "tier": tier_from_emoji(tier_cell),
            "vs": vs_from_cell(tier_cell),
        }

    # Section-level note: capture first non-empty line mentioning AI/判定 after the header suffix
    section_note = header_suffix
    # Also capture "結論" line for context
    con_m = re.search(r'\*\*結論\*\*\s*[:：]\s*(.*)', body)
    conclusion = con_m.group(1).strip() if con_m else None

    l1_data[code] = {
        "name": cn,
        "section_note": section_note,
        "conclusion": conclusion,
        "l2": entries,
    }

# Join with l2_l3_ie/*.json row counts (historical frequency proxy)
# AND backfill missing L2s from xlsx L2 names when the markdown table
# was narrative-only for that L1 (per user Q1 answer: "(b) 從 l2_l3_ie
# 的 xlsx L2 名字反向建表、feature 暫留空").
for l1_code, info in l1_data.items():
    path = f'l2_l3_ie/{l1_code}.json'
    if not os.path.exists(path): continue
    ie = json.load(open(path, encoding='utf-8'))
    # Count rows across knit + woven for each L2 NAME
    freq = {}
    for fk in ('knit', 'woven'):
        for l2 in ie.get(fk, []):
            name = l2.get('l2')
            total = 0
            for sh in l2.get('shapes', []):
                for method in sh.get('methods', []):
                    total += len(method.get('steps', []))
            freq[name] = freq.get(name, 0) + total
    info['freq_by_l2_name'] = freq

    # Map existing markdown-derived entries by name for overlap detection.
    existing_names = {v['name']: k for k, v in info['l2'].items()}

    # Backfill: any xlsx L2 name without a matching report entry becomes
    # an 'unknown'-tier stub keyed by the xlsx name itself. UI / AI
    # prompt still see it, just without an explicit visual feature —
    # user can fill the feature text in later.
    for xlsx_name, f in sorted(freq.items(), key=lambda kv: -kv[1]):
        if xlsx_name in existing_names: continue
        # Use xlsx name as both key and display name; skip ** catch-all buckets.
        if xlsx_name.startswith('**'): continue
        info['l2'][xlsx_name] = {
            "name": xlsx_name,
            "feature": "",
            "tier": "unknown",
            "vs": None,
            "freq": f,
            "source": "xlsx_backfill"
        }

    # Also attach freq to existing markdown-derived entries when we can match
    # the name (soft match — markdown names often don't match xlsx names literally).
    for l2_code, entry in info['l2'].items():
        if 'freq' in entry: continue
        entry['freq'] = freq.get(entry['name'], 0)
        entry['source'] = entry.get('source', 'markdown')

# Rebuild SL section's missing 015 note explicitly
# (The report says SL has 15 L2 but the table skips 015 and includes 016.)
# Nothing to fix here — parser already records whatever is in the table.

out = {
    "version": "v1",
    "created": "2026-04-17",
    "source_markdown": "L2_Visual_Differentiation_FullAnalysis.md",
    "tier_rules": {
        "green":   "AI 可直接用視覺判定",
        "yellow":  "需看細節但有望可行",
        "red":     "AI 無法從 sketch 判定,需 IE 文字或歷史資料補足",
        "unknown": "報告未標註(例如 L1 只有 1 個 L2 無須區分,或屬於敘事段落未入表)"
    },
    "l1": l1_data,
}

os.makedirs('data', exist_ok=True)
with open('data/l2_visual_guide.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

# Summary
total_l2 = sum(len(v['l2']) for v in l1_data.values())
by_tier = {'green':0,'yellow':0,'red':0,'unknown':0}
for v in l1_data.values():
    for l2 in v['l2'].values():
        by_tier[l2['tier']] = by_tier.get(l2['tier'],0) + 1
print(f'L1 sections: {len(l1_data)}')
print(f'L2 entries extracted: {total_l2}')
print(f'Tier breakdown: {by_tier}')
print(f'Output: data/l2_visual_guide.json ({os.path.getsize("data/l2_visual_guide.json")/1024:.1f} KB)')
