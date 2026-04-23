#!/usr/bin/env python3
"""
normalize_consensus.py — Convert consensus_rules_final.json into star schema format.

Input:  consensus_rules_final.json (275 rules, bucket×fingerprint×zone level)
Output: data/ingest/consensus_rules/facts.jsonl (normalized zone names → l1_standard_38)

The consensus_rules are ALREADY aggregated across designs, so they don't produce dim.jsonl.
Each rule becomes a fact with composite key: bucket × fingerprint × zone.
"""

import json
import re
from pathlib import Path
from collections import defaultdict

# ── L1 Standard 38 (authoritative zh names from build_run v4.3) ──
L1_STANDARD_38 = {
    "AE": "袖孔", "AH": "袖圍", "BM": "下襬", "BN": "貼合", "BP": "襬叉",
    "BS": "釦鎖", "DC": "繩類", "DP": "裝飾片", "FP": "袋蓋", "FY": "前立",
    "HD": "帽子", "HL": "釦環", "KH": "Keyhole", "LB": "商標", "LI": "裡布",
    "LO": "褲口", "LP": "帶絆", "NK": "領", "NP": "領襟", "NT": "領貼條",
    "OT": "其它", "PD": "褶", "PK": "口袋", "PL": "門襟", "PS": "褲合身",
    "QT": "行縫(固定棉)", "RS": "褲襠", "SA": "剪接線_上身類", "SB": "剪接線_下身類",
    "SH": "肩", "SL": "袖口", "SP": "袖叉", "SR": "裙合身", "SS": "脅邊",
    "ST": "肩帶", "TH": "拇指洞", "WB": "腰頭", "ZP": "拉鍊",
}
ZH_TO_L1 = {v: k for k, v in L1_STANDARD_38.items()}

# Consensus zone alias → (l1_code, canonical zh)
ZONE_ALIAS = {
    # Direct matches (already in l1_standard_38)
    "下襬": ("BM", "下襬"),
    "口袋": ("PK", "口袋"),
    "帽子": ("HD", "帽子"),
    "肩": ("SH", "肩"),
    "腰頭": ("WB", "腰頭"),
    "袖口": ("SL", "袖口"),
    "袖孔": ("AE", "袖孔"),
    "褲口": ("LO", "褲口"),
    "褲合身": ("PS", "褲合身"),
    "領": ("NK", "領"),
    # Aliases (need remapping)
    "前拉鍊": ("ZP", "拉鍊"),
    "前襟": ("PL", "門襟"),
    "滾邊": ("NT", "領貼條"),   # binding → most commonly at neck
    "脇邊": ("SS", "脅邊"),     # same meaning, different character (脇=脅)
    "腰線": ("WB", "腰頭"),     # waistline ≈ waistband zone
    "車縫(通則)": ("_DEFAULT", "車縫(通則)"),  # general stitching
}


def normalize_consensus(source_path, output_dir):
    """Normalize consensus_rules zones and output as facts.jsonl."""
    rules = json.loads(Path(source_path).read_text(encoding='utf-8'))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    facts = []
    unmapped_zones = set()

    for rule in rules:
        zone_raw = rule['zone']
        alias = ZONE_ALIAS.get(zone_raw)

        if alias is None:
            unmapped_zones.add(zone_raw)
            continue

        l1_code, zone_zh = alias
        specs = rule.get('specs', {})

        # Extract ISO from specs
        iso = specs.get('iso')
        combo = specs.get('combo')
        method = specs.get('method')

        fact = {
            'bucket': rule['bucket'],
            'fingerprint': rule['fingerprint'],
            'zone_zh': zone_zh,
            'l1_code': l1_code,
            'iso': iso,
            'combo': combo,
            'method': method,
            'confidence': rule.get('confidence', 'unknown'),
            'fp_total': rule.get('fp_total'),
            'zone_coverage': rule.get('zone_coverage'),
            'iso_share': specs.get('iso_share') or specs.get('combo_share'),
            'margin': specs.get('margin'),
            'source': 'consensus_rules_final',
        }
        facts.append(fact)

    # Write output
    facts_path = out / 'facts.jsonl'
    with open(facts_path, 'w', encoding='utf-8') as f:
        for fact in facts:
            f.write(json.dumps(fact, ensure_ascii=False) + '\n')

    # Stats
    print(f"{'='*60}")
    print(f"CONSENSUS NORMALIZATION COMPLETE")
    print(f"{'='*60}")
    print(f"Input rules:         {len(rules)}")
    print(f"Output facts:        {len(facts)}")
    print(f"Unmapped zones:      {unmapped_zones or 'none'}")

    # Zone distribution
    zone_dist = defaultdict(int)
    for f in facts:
        zone_dist[f'{f["zone_zh"]}({f["l1_code"]})'] += 1
    print(f"\n--- Zone Distribution ---")
    for z, n in sorted(zone_dist.items(), key=lambda x: -x[1]):
        print(f"  {z}: {n}")

    # Bucket coverage
    buckets = set(f['bucket'] for f in facts)
    print(f"\nBuckets covered: {len(buckets)}")

    print(f"\nOutput: {facts_path} ({len(facts)} rows)")
    return facts


if __name__ == '__main__':
    _star = Path(__file__).resolve().parent.parent
    _ony = _star.parent
    SOURCE = str(_ony / "pom_analysis_v5.5.1" / "data" / "consensus_rules_final.json")
    OUTPUT = str(_star / "data" / "ingest" / "consensus_v1")
    normalize_consensus(SOURCE, OUTPUT)
