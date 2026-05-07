"""
Parse L2_VLM_Decision_Tree_Prompts_v2.md → data/l2_decision_trees.json

Structure expected in source:
  ## §0 通用 System Prompt
  ```
  <common system prompt body>
  ```
  ## §AE — 袖孔（9 L2）⚠️ 大類易分，內部工法難
  ```
  判定邏輯：...
  ```
  ... (38 L1 sections)

Output JSON:
  {
    "version": "v2",
    "created": "<YYYY-MM-DD>",
    "source": "L2_VLM_Decision_Tree_Prompts_v2.md",
    "common": "<body of §0 code block>",
    "l1": {
      "AE": { "note": "大類易分，內部工法難", "tree": "<body of §AE code block>" },
      ...
    }
  }
"""

import json
import re
import os
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = str(REPO_ROOT / 'docs' / 'spec' / 'L2_VLM_Decision_Tree_Prompts_v2.md')
OUT = str(REPO_ROOT / 'data' / 'runtime' / 'l2_decision_trees.json')

with open(SRC, encoding='utf-8') as f:
    md = f.read()

# Find all §X headers with their body code block
# Pattern: ## §<id> <rest>\n\n```\n<body>\n```
HEADER_RE = re.compile(r'^## §([0A-Z]{1,2})\s*[^\n]*$', re.M)
CODE_RE = re.compile(r'^```\s*\n([\s\S]*?)\n```', re.M)

# Short note stripped from header tail: take everything after 分類 emoji
NOTE_RE = re.compile(r'[⚠️✅🟢🟡🔴]\s*(.+?)\s*$')

sections = []
for m in HEADER_RE.finditer(md):
    sections.append((m.group(1), m.start(), m.end(), md[m.start():m.end()]))

common_text = ""
l1_map = {}
for i, (code, start, header_end, header_line) in enumerate(sections):
    body_start = header_end
    body_end = sections[i+1][1] if i+1 < len(sections) else len(md)
    body_slice = md[body_start:body_end]
    cm = CODE_RE.search(body_slice)
    if not cm:
        print(f'⚠ no code block under §{code}')
        continue
    block = cm.group(1).strip()
    if code == '0':
        common_text = block
    else:
        note_m = NOTE_RE.search(header_line)
        note = note_m.group(1).strip() if note_m else ""
        l1_map[code] = {"note": note, "tree": block}

out = {
    "version": "v2",
    "created": datetime.date.today().isoformat(),
    "source": SRC,
    "common": common_text,
    "l1": l1_map,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

# Stats
print(f'common prompt chars: {len(common_text)}')
print(f'L1 trees extracted: {len(l1_map)}')
missing = sorted(set([
    'AE','AH','BM','BN','BP','BS','DC','DP','FP','FY','HD','HL','KH','LB','LI',
    'LO','LP','NK','NP','NT','OT','PD','PK','PL','PS','QT','RS','SA','SB','SH',
    'SL','SP','SR','SS','ST','TH','WB','ZP'
]) - set(l1_map.keys()))
if missing:
    print(f'⚠ missing L1 codes: {missing}')
else:
    print('✓ all 38 L1 codes covered')
avg_tree_len = sum(len(v['tree']) for v in l1_map.values()) / max(1, len(l1_map))
max_tree_len = max((len(v['tree']) for v in l1_map.values()), default=0)
print(f'tree chars — avg: {avg_tree_len:.0f}, max: {max_tree_len}')
print(f'Output: {OUT} ({os.path.getsize(OUT)/1024:.1f} KB)')
